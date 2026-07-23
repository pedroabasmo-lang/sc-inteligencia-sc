-- ============================================================================
-- 14_candidate_campaign_profiles.sql — Perfil permanente do candidato e perfil
-- estratégico da candidatura (duas camadas), com RLS, auditoria e RPC de upsert.
--
-- Cria: public.candidate_profiles, public.campaign_strategy_profiles,
-- funções de auditoria + triggers, policies RLS, índices, a RPC
-- public.save_campaign_candidate_profile e comentários. Não altera migrations
-- 01–13, campaigns, o núcleo do Modelo C nem o frontend.
--
-- DUAS CAMADAS:
--  - candidate_profiles: identidade PERMANENTE do candidato (independe da eleição),
--    escopo (org_id, candidate_id), no máximo um perfil ativo por candidato/org.
--  - campaign_strategy_profiles: ESTRATÉGIA de uma candidatura específica, escopo
--    (org_id, campaign_id, candidacy_id, candidate_id), no máximo um ativo por campanha.
-- Dados eleitorais (ano, cargo, número, partido, UF, nome de urna) NÃO são
-- duplicados aqui — pertencem a candidacies.
--
-- ISOLAMENTO: dados privados por organização/campanha (RLS). Não afeta o acesso
-- aos dados públicos eleitorais/territoriais do restante do sistema, nem limita
-- usuário a um único estado.
--
-- AUTORIZAÇÃO: reutiliza is_org_dono (proprietário real), can_read_candidate,
-- is_campaign_member e campaign_role (migrations 02/10). Escrita: proprietário
-- da organização ou admin da campanha. Auditoria pelos triggers desta migration.
-- ============================================================================
BEGIN;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. candidate_profiles — identidade permanente.
-- ─────────────────────────────────────────────────────────────────────────
create table public.candidate_profiles (
  id                      uuid not null default gen_random_uuid(),
  org_id                  uuid not null,
  candidate_id            uuid not null,
  nome_publico            text,
  biografia_curta         text,
  biografia_completa      text,
  profissao               text,
  formacao                text,
  cidade_base             text,
  uf_base                 text,
  trajetoria_politica     text,
  trajetoria_profissional text,
  trajetoria_social       text,
  causas_historicas       text,
  realizacoes             text,
  redes_sociais           jsonb,
  canais_publicos         jsonb,
  foto_url                text,
  observacoes_internas    text,
  archived_at             timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  created_by              uuid,
  updated_by              uuid,
  constraint candidate_profiles_pkey primary key (id),
  constraint candidate_profiles_org_fk      foreign key (org_id)     references public.organizations(id) on delete restrict,
  constraint candidate_profiles_cand_org_fk foreign key (candidate_id, org_id) references public.candidates(id, org_id) on delete restrict,
  constraint candidate_profiles_created_fk  foreign key (created_by) references public.profiles(id) on delete set null,
  constraint candidate_profiles_updated_fk  foreign key (updated_by) references public.profiles(id) on delete set null,
  constraint candidate_profiles_uf_chk      check (uf_base is null or uf_base ~ '^[A-Z]{2}$'),
  constraint candidate_profiles_redes_chk   check (redes_sociais   is null or jsonb_typeof(redes_sociais)   = 'object'),
  constraint candidate_profiles_canais_chk  check (canais_publicos is null or jsonb_typeof(canais_publicos) = 'object')
);
-- Um único perfil permanente ATIVO por candidato dentro da organização.
create unique index candidate_profiles_ativo_uk
  on public.candidate_profiles(org_id, candidate_id) where archived_at is null;
create index candidate_profiles_org_idx  on public.candidate_profiles(org_id);
create index candidate_profiles_cand_idx on public.candidate_profiles(candidate_id);

-- ─────────────────────────────────────────────────────────────────────────
-- 2. campaign_strategy_profiles — estratégia da candidatura.
-- ─────────────────────────────────────────────────────────────────────────
create table public.campaign_strategy_profiles (
  id                     uuid not null default gen_random_uuid(),
  org_id                 uuid not null,
  campaign_id            uuid not null,
  candidacy_id           uuid not null,
  candidate_id           uuid not null,
  -- Direcionamento
  objetivo_eleitoral     text,
  objetivo_politico      text,
  posicionamento         text,
  mensagem_central       text,
  slogan                 text,
  narrativa_principal    text,
  proposta_de_valor      text,
  -- Públicos e território
  publicos_prioritarios  jsonb,
  segmentos_prioritarios jsonb,
  territorios_prioritarios jsonb,
  municipios_prioritarios jsonb,
  grupos_de_apoio        jsonb,
  grupos_de_resistencia  jsonb,
  -- Agenda
  temas_prioritarios     jsonb,
  propostas_prioritarias jsonb,
  compromissos_publicos  jsonb,
  bandeiras_centrais     jsonb,
  -- Diagnóstico
  fortalezas             text,
  vulnerabilidades       text,
  oportunidades          text,
  ameacas                text,
  riscos_reputacionais   text,
  pontos_de_atencao      text,
  -- Comunicação
  tom_de_voz             text,
  palavras_chave         jsonb,
  palavras_a_evitar      jsonb,
  identidade_narrativa   text,
  orientacoes_de_imagem  text,
  -- Organização
  prioridades_imediatas  jsonb,
  metas_de_curto_prazo   jsonb,
  metas_de_medio_prazo   jsonb,
  observacoes_internas   text,
  status                 text not null default 'rascunho',
  -- Controle
  archived_at            timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  created_by             uuid,
  updated_by             uuid,
  constraint campaign_strategy_profiles_pkey primary key (id),
  constraint csp_org_fk       foreign key (org_id)      references public.organizations(id) on delete restrict,
  constraint csp_campaign_fk  foreign key (campaign_id, org_id)  references public.campaigns(id, org_id)   on delete restrict,
  constraint csp_candidacy_fk foreign key (candidacy_id, org_id) references public.candidacies(id, org_id) on delete restrict,
  constraint csp_candidate_fk foreign key (candidate_id, org_id) references public.candidates(id, org_id)  on delete restrict,
  constraint csp_created_fk   foreign key (created_by)  references public.profiles(id) on delete set null,
  constraint csp_updated_fk   foreign key (updated_by)  references public.profiles(id) on delete set null,
  constraint csp_status_chk   check (status in ('rascunho','em_construcao','validado','suspenso','encerrado')),
  constraint csp_publicos_chk    check (publicos_prioritarios   is null or jsonb_typeof(publicos_prioritarios)   = 'array'),
  constraint csp_segmentos_chk   check (segmentos_prioritarios  is null or jsonb_typeof(segmentos_prioritarios)  = 'array'),
  constraint csp_territorios_chk check (territorios_prioritarios is null or jsonb_typeof(territorios_prioritarios) = 'array'),
  constraint csp_municipios_chk  check (municipios_prioritarios  is null or jsonb_typeof(municipios_prioritarios)  = 'array'),
  constraint csp_gapoio_chk      check (grupos_de_apoio          is null or jsonb_typeof(grupos_de_apoio)          = 'array'),
  constraint csp_gresist_chk     check (grupos_de_resistencia    is null or jsonb_typeof(grupos_de_resistencia)    = 'array'),
  constraint csp_temas_chk       check (temas_prioritarios       is null or jsonb_typeof(temas_prioritarios)       = 'array'),
  constraint csp_propostas_chk   check (propostas_prioritarias   is null or jsonb_typeof(propostas_prioritarias)   = 'array'),
  constraint csp_compromissos_chk check (compromissos_publicos   is null or jsonb_typeof(compromissos_publicos)    = 'array'),
  constraint csp_bandeiras_chk   check (bandeiras_centrais       is null or jsonb_typeof(bandeiras_centrais)       = 'array'),
  constraint csp_palchave_chk    check (palavras_chave           is null or jsonb_typeof(palavras_chave)           = 'array'),
  constraint csp_palevitar_chk   check (palavras_a_evitar        is null or jsonb_typeof(palavras_a_evitar)        = 'array'),
  constraint csp_prioridades_chk check (prioridades_imediatas    is null or jsonb_typeof(prioridades_imediatas)    = 'array'),
  constraint csp_metascurto_chk  check (metas_de_curto_prazo     is null or jsonb_typeof(metas_de_curto_prazo)     = 'array'),
  constraint csp_metasmedio_chk  check (metas_de_medio_prazo     is null or jsonb_typeof(metas_de_medio_prazo)     = 'array')
);
-- Um único perfil estratégico ATIVO por campanha.
create unique index csp_ativo_uk on public.campaign_strategy_profiles(campaign_id) where archived_at is null;
create index csp_org_idx       on public.campaign_strategy_profiles(org_id);
create index csp_candidacy_idx on public.campaign_strategy_profiles(candidacy_id);
create index csp_candidate_idx on public.campaign_strategy_profiles(candidate_id);

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Auditoria (reutiliza public.audit_log; padrão das migrations 03/10).
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.audita_candidate_profiles()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (null, auth.uid(), tg_op, 'candidate_profiles', new.id::text,
          case when tg_op = 'UPDATE' then to_jsonb(old) else null end, to_jsonb(new));
  return null;
end; $$;

create or replace function public.audita_campaign_strategy_profiles()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (new.campaign_id, auth.uid(), tg_op, 'campaign_strategy_profiles', new.id::text,
          case when tg_op = 'UPDATE' then to_jsonb(old) else null end, to_jsonb(new));
  return null;
end; $$;

revoke all on function public.audita_candidate_profiles()          from public, anon;
revoke all on function public.audita_campaign_strategy_profiles()  from public, anon;

create trigger trg_audita_candidate_profiles
  after insert or update on public.candidate_profiles
  for each row execute function public.audita_candidate_profiles();
create trigger trg_audita_campaign_strategy_profiles
  after insert or update on public.campaign_strategy_profiles
  for each row execute function public.audita_campaign_strategy_profiles();

-- ─────────────────────────────────────────────────────────────────────────
-- 4. RLS — ESCRITA SOMENTE PELA RPC. Apenas policies de SELECT (leitura autorizada).
--    Nenhuma policy de INSERT/UPDATE/DELETE: toda escrita passa pela RPC
--    save_campaign_candidate_profile (SECURITY DEFINER), que valida proprietário/
--    admin e a integridade do Modelo C. authenticated não faz DML direto — só SELECT.
-- ─────────────────────────────────────────────────────────────────────────
alter table public.candidate_profiles          enable row level security;
alter table public.campaign_strategy_profiles  enable row level security;

-- candidate_profiles: leitura ao dono ou a membro de campanha vinculada ao candidato.
create policy p_candprof_sel on public.candidate_profiles for select to authenticated
  using (public.is_org_dono(org_id) or public.can_read_candidate(candidate_id));

-- campaign_strategy_profiles: leitura ao dono ou membro da campanha.
create policy p_csp_sel on public.campaign_strategy_profiles for select to authenticated
  using (public.is_org_dono(org_id) or public.is_campaign_member(campaign_id));

-- Privilégios: sem DML direto (nem para authenticated); apenas SELECT sujeito à RLS.
revoke all on public.candidate_profiles          from public, anon, authenticated;
revoke all on public.campaign_strategy_profiles  from public, anon, authenticated;
grant select on public.candidate_profiles          to authenticated;
grant select on public.campaign_strategy_profiles  to authenticated;

-- ─────────────────────────────────────────────────────────────────────────
-- 5. RPC transacional de upsert dos dois perfis.
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.save_campaign_candidate_profile(
  p_campaign_id uuid,
  p_org         uuid,
  -- Perfil permanente
  p_nome_publico text,
  p_biografia_curta text,
  p_biografia_completa text,
  p_profissao text,
  p_formacao text,
  p_cidade_base text,
  p_uf_base text,
  p_trajetoria_politica text,
  p_trajetoria_profissional text,
  p_trajetoria_social text,
  p_causas_historicas text,
  p_realizacoes text,
  p_redes_sociais jsonb,
  p_canais_publicos jsonb,
  p_foto_url text,
  p_observacoes_candidato text,
  -- Estratégia
  p_objetivo_eleitoral text,
  p_objetivo_politico text,
  p_posicionamento text,
  p_mensagem_central text,
  p_slogan text,
  p_narrativa_principal text,
  p_proposta_de_valor text,
  p_publicos_prioritarios jsonb,
  p_segmentos_prioritarios jsonb,
  p_territorios_prioritarios jsonb,
  p_municipios_prioritarios jsonb,
  p_grupos_de_apoio jsonb,
  p_grupos_de_resistencia jsonb,
  p_temas_prioritarios jsonb,
  p_propostas_prioritarias jsonb,
  p_compromissos_publicos jsonb,
  p_bandeiras_centrais jsonb,
  p_fortalezas text,
  p_vulnerabilidades text,
  p_oportunidades text,
  p_ameacas text,
  p_riscos_reputacionais text,
  p_pontos_de_atencao text,
  p_tom_de_voz text,
  p_palavras_chave jsonb,
  p_palavras_a_evitar jsonb,
  p_identidade_narrativa text,
  p_orientacoes_de_imagem text,
  p_prioridades_imediatas jsonb,
  p_metas_de_curto_prazo jsonb,
  p_metas_de_medio_prazo jsonb,
  p_observacoes_estrategia text,
  p_status text
)
returns table (
  campaign_id             uuid,
  candidate_id            uuid,
  candidacy_id            uuid,
  candidate_profile_id    uuid,
  strategy_profile_id     uuid,
  candidate_profile_criado boolean,
  strategy_profile_criado  boolean,
  ja_estava_atualizado     boolean
)
language plpgsql security definer set search_path = ''
as $$
declare
  v_uid       uuid := auth.uid();
  v_dono      uuid;
  v_is_admin  boolean;
  v_c         record;   -- campaigns
  v_cy        record;   -- candidacies
  v_cm        record;   -- candidacy_members principal
  v_cand      record;   -- candidates
  v_cp        record;   -- candidate_profiles existente
  v_sp        record;   -- strategy existente
  v_uf        text;
  v_status    text;
  v_cp_id     uuid;
  v_sp_id     uuid;
  v_cp_novo   boolean := false;
  v_sp_novo   boolean := false;
  v_cp_muda   boolean;
  v_sp_muda   boolean;
  -- textos normalizados (permanente)
  n_nome text; n_biocurta text; n_biocompleta text; n_prof text; n_form text;
  n_cidade text; n_trajpol text; n_trajprof text; n_trajsoc text; n_causas text;
  n_realiz text; n_foto text; n_obscand text;
  -- textos normalizados (estratégia)
  n_objele text; n_objpol text; n_posic text; n_msg text; n_slogan text; n_narr text;
  n_propval text; n_fort text; n_vuln text; n_oport text; n_amea text; n_risco text;
  n_aten text; n_tom text; n_idnarr text; n_orimg text; n_obsest text;
begin
  if v_uid is null then raise exception 'Não autenticado.'; end if;
  if p_campaign_id is null then raise exception 'p_campaign_id é obrigatório.'; end if;
  if p_org is null then raise exception 'Organização não informada.'; end if;

  -- Concorrência: serializa por campanha (mesma convenção das migrations 12/13).
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_campaign_id::text, 0));

  -- Bloqueios em ordem determinística.
  select o.dono_id into v_dono from public.organizations o where o.id = p_org for update;
  if not found then raise exception 'Organização inexistente.'; end if;

  select c.* into v_c from public.campaigns c where c.id = p_campaign_id for update;
  if not found then raise exception 'Campanha inexistente.'; end if;
  if v_c.org_id is distinct from p_org then raise exception 'Campanha pertence a outra organização.'; end if;
  if v_c.archived_at is not null then raise exception 'Campanha arquivada não pode receber perfil.'; end if;

  -- Autorização: proprietário real OU admin da campanha (papel real em campaign_members).
  v_is_admin := exists (select 1 from public.campaign_members m
                         where m.campaign_id = p_campaign_id and m.user_id = v_uid and m.papel = 'admin');
  if not (v_dono = v_uid or v_is_admin) then
    raise exception 'Apenas o proprietário da organização ou o admin da campanha pode salvar o perfil.';
  end if;

  -- Estrutura do Modelo C (uma candidatura, um principal, candidato íntegro).
  select cy.* into v_cy from public.candidacies cy where cy.campaign_id = p_campaign_id for update;
  if not found then raise exception 'Campanha sem candidatura: requer correção estrutural.'; end if;
  if v_cy.org_id is distinct from p_org then raise exception 'Inconsistência: candidatura de organização diferente.'; end if;

  select cm.* into v_cm from public.candidacy_members cm
    where cm.candidacy_id = v_cy.id and cm.is_principal = true for update;
  if not found then raise exception 'Candidatura sem membro principal: requer correção estrutural.'; end if;

  select cand.* into v_cand from public.candidates cand where cand.id = v_cm.candidate_id for update;
  if not found then raise exception 'Membro principal sem candidato: requer correção estrutural.'; end if;
  if v_cand.org_id is distinct from p_org then raise exception 'Inconsistência: candidato de organização diferente.'; end if;
  if v_cand.deleted_at is not null then raise exception 'Candidato principal está excluído: requer correção estrutural.'; end if;

  -- Lock adicional por candidate (namespace 'candidate:'), pois o candidate_profile
  -- é compartilhado entre campanhas do mesmo candidato — o lock de campanha não
  -- basta para serializar duas campanhas distintas atualizando o mesmo perfil.
  -- O lock de campanha acima permanece SEM prefixo (compatível com migrations 12/13).
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('candidate:'||v_cand.id::text, 0));

  -- Validação de UF base, status e JSONB.
  if p_uf_base is null or btrim(p_uf_base) = '' then
    v_uf := null;
  else
    v_uf := upper(btrim(p_uf_base));
    if v_uf !~ '^[A-Z]{2}$' then raise exception 'UF base inválida: "%".', p_uf_base; end if;
  end if;
  v_status := coalesce(nullif(btrim(coalesce(p_status,'')),''),'rascunho');
  if v_status not in ('rascunho','em_construcao','validado','suspenso','encerrado') then
    raise exception 'Status inválido: "%".', p_status;
  end if;
  -- JSONB objetos
  if p_redes_sociais    is not null and jsonb_typeof(p_redes_sociais)    <> 'object' then raise exception 'redes_sociais deve ser objeto JSON.'; end if;
  if p_canais_publicos  is not null and jsonb_typeof(p_canais_publicos)  <> 'object' then raise exception 'canais_publicos deve ser objeto JSON.'; end if;
  -- JSONB arrays
  if p_publicos_prioritarios   is not null and jsonb_typeof(p_publicos_prioritarios)   <> 'array' then raise exception 'publicos_prioritarios deve ser array JSON.'; end if;
  if p_segmentos_prioritarios  is not null and jsonb_typeof(p_segmentos_prioritarios)  <> 'array' then raise exception 'segmentos_prioritarios deve ser array JSON.'; end if;
  if p_territorios_prioritarios is not null and jsonb_typeof(p_territorios_prioritarios) <> 'array' then raise exception 'territorios_prioritarios deve ser array JSON.'; end if;
  if p_municipios_prioritarios is not null and jsonb_typeof(p_municipios_prioritarios) <> 'array' then raise exception 'municipios_prioritarios deve ser array JSON.'; end if;
  if p_grupos_de_apoio         is not null and jsonb_typeof(p_grupos_de_apoio)         <> 'array' then raise exception 'grupos_de_apoio deve ser array JSON.'; end if;
  if p_grupos_de_resistencia   is not null and jsonb_typeof(p_grupos_de_resistencia)   <> 'array' then raise exception 'grupos_de_resistencia deve ser array JSON.'; end if;
  if p_temas_prioritarios      is not null and jsonb_typeof(p_temas_prioritarios)      <> 'array' then raise exception 'temas_prioritarios deve ser array JSON.'; end if;
  if p_propostas_prioritarias  is not null and jsonb_typeof(p_propostas_prioritarias)  <> 'array' then raise exception 'propostas_prioritarias deve ser array JSON.'; end if;
  if p_compromissos_publicos   is not null and jsonb_typeof(p_compromissos_publicos)   <> 'array' then raise exception 'compromissos_publicos deve ser array JSON.'; end if;
  if p_bandeiras_centrais      is not null and jsonb_typeof(p_bandeiras_centrais)      <> 'array' then raise exception 'bandeiras_centrais deve ser array JSON.'; end if;
  if p_palavras_chave          is not null and jsonb_typeof(p_palavras_chave)          <> 'array' then raise exception 'palavras_chave deve ser array JSON.'; end if;
  if p_palavras_a_evitar       is not null and jsonb_typeof(p_palavras_a_evitar)       <> 'array' then raise exception 'palavras_a_evitar deve ser array JSON.'; end if;
  if p_prioridades_imediatas   is not null and jsonb_typeof(p_prioridades_imediatas)   <> 'array' then raise exception 'prioridades_imediatas deve ser array JSON.'; end if;
  if p_metas_de_curto_prazo    is not null and jsonb_typeof(p_metas_de_curto_prazo)    <> 'array' then raise exception 'metas_de_curto_prazo deve ser array JSON.'; end if;
  if p_metas_de_medio_prazo    is not null and jsonb_typeof(p_metas_de_medio_prazo)    <> 'array' then raise exception 'metas_de_medio_prazo deve ser array JSON.'; end if;

  -- Normalização de textos (btrim; vazio → null; conteúdo narrativo preservado).
  n_nome:=nullif(btrim(coalesce(p_nome_publico,'')),''); n_biocurta:=nullif(btrim(coalesce(p_biografia_curta,'')),'');
  n_biocompleta:=nullif(btrim(coalesce(p_biografia_completa,'')),''); n_prof:=nullif(btrim(coalesce(p_profissao,'')),'');
  n_form:=nullif(btrim(coalesce(p_formacao,'')),''); n_cidade:=nullif(btrim(coalesce(p_cidade_base,'')),'');
  n_trajpol:=nullif(btrim(coalesce(p_trajetoria_politica,'')),''); n_trajprof:=nullif(btrim(coalesce(p_trajetoria_profissional,'')),'');
  n_trajsoc:=nullif(btrim(coalesce(p_trajetoria_social,'')),''); n_causas:=nullif(btrim(coalesce(p_causas_historicas,'')),'');
  n_realiz:=nullif(btrim(coalesce(p_realizacoes,'')),''); n_foto:=nullif(btrim(coalesce(p_foto_url,'')),'');
  n_obscand:=nullif(btrim(coalesce(p_observacoes_candidato,'')),'');
  n_objele:=nullif(btrim(coalesce(p_objetivo_eleitoral,'')),''); n_objpol:=nullif(btrim(coalesce(p_objetivo_politico,'')),'');
  n_posic:=nullif(btrim(coalesce(p_posicionamento,'')),''); n_msg:=nullif(btrim(coalesce(p_mensagem_central,'')),'');
  n_slogan:=nullif(btrim(coalesce(p_slogan,'')),''); n_narr:=nullif(btrim(coalesce(p_narrativa_principal,'')),'');
  n_propval:=nullif(btrim(coalesce(p_proposta_de_valor,'')),''); n_fort:=nullif(btrim(coalesce(p_fortalezas,'')),'');
  n_vuln:=nullif(btrim(coalesce(p_vulnerabilidades,'')),''); n_oport:=nullif(btrim(coalesce(p_oportunidades,'')),'');
  n_amea:=nullif(btrim(coalesce(p_ameacas,'')),''); n_risco:=nullif(btrim(coalesce(p_riscos_reputacionais,'')),'');
  n_aten:=nullif(btrim(coalesce(p_pontos_de_atencao,'')),''); n_tom:=nullif(btrim(coalesce(p_tom_de_voz,'')),'');
  n_idnarr:=nullif(btrim(coalesce(p_identidade_narrativa,'')),''); n_orimg:=nullif(btrim(coalesce(p_orientacoes_de_imagem,'')),'');
  n_obsest:=nullif(btrim(coalesce(p_observacoes_estrategia,'')),'');

  -- ── candidate_profiles: upsert ──
  select cp.* into v_cp from public.candidate_profiles cp
    where cp.org_id = p_org and cp.candidate_id = v_cand.id and cp.archived_at is null for update;
  if not found then
    insert into public.candidate_profiles(
      org_id, candidate_id, nome_publico, biografia_curta, biografia_completa, profissao, formacao,
      cidade_base, uf_base, trajetoria_politica, trajetoria_profissional, trajetoria_social,
      causas_historicas, realizacoes, redes_sociais, canais_publicos, foto_url, observacoes_internas,
      created_by, updated_by)
    values (
      p_org, v_cand.id, n_nome, n_biocurta, n_biocompleta, n_prof, n_form,
      n_cidade, v_uf, n_trajpol, n_trajprof, n_trajsoc,
      n_causas, n_realiz, p_redes_sociais, p_canais_publicos, n_foto, n_obscand,
      v_uid, v_uid)
    returning id into v_cp_id;
    v_cp_novo := true;
  else
    v_cp_id := v_cp.id;
    v_cp_muda := (
         v_cp.nome_publico is distinct from n_nome
      or v_cp.biografia_curta is distinct from n_biocurta
      or v_cp.biografia_completa is distinct from n_biocompleta
      or v_cp.profissao is distinct from n_prof
      or v_cp.formacao is distinct from n_form
      or v_cp.cidade_base is distinct from n_cidade
      or v_cp.uf_base is distinct from v_uf
      or v_cp.trajetoria_politica is distinct from n_trajpol
      or v_cp.trajetoria_profissional is distinct from n_trajprof
      or v_cp.trajetoria_social is distinct from n_trajsoc
      or v_cp.causas_historicas is distinct from n_causas
      or v_cp.realizacoes is distinct from n_realiz
      or v_cp.redes_sociais is distinct from p_redes_sociais
      or v_cp.canais_publicos is distinct from p_canais_publicos
      or v_cp.foto_url is distinct from n_foto
      or v_cp.observacoes_internas is distinct from n_obscand
    );
    if v_cp_muda then
      update public.candidate_profiles set
        nome_publico=n_nome, biografia_curta=n_biocurta, biografia_completa=n_biocompleta,
        profissao=n_prof, formacao=n_form, cidade_base=n_cidade, uf_base=v_uf,
        trajetoria_politica=n_trajpol, trajetoria_profissional=n_trajprof, trajetoria_social=n_trajsoc,
        causas_historicas=n_causas, realizacoes=n_realiz, redes_sociais=p_redes_sociais,
        canais_publicos=p_canais_publicos, foto_url=n_foto, observacoes_internas=n_obscand,
        updated_by=v_uid, updated_at=now()
      where id = v_cp_id;
    end if;
  end if;

  -- ── campaign_strategy_profiles: upsert ──
  select sp.* into v_sp from public.campaign_strategy_profiles sp
    where sp.campaign_id = p_campaign_id and sp.archived_at is null for update;
  if not found then
    insert into public.campaign_strategy_profiles(
      org_id, campaign_id, candidacy_id, candidate_id,
      objetivo_eleitoral, objetivo_politico, posicionamento, mensagem_central, slogan, narrativa_principal, proposta_de_valor,
      publicos_prioritarios, segmentos_prioritarios, territorios_prioritarios, municipios_prioritarios, grupos_de_apoio, grupos_de_resistencia,
      temas_prioritarios, propostas_prioritarias, compromissos_publicos, bandeiras_centrais,
      fortalezas, vulnerabilidades, oportunidades, ameacas, riscos_reputacionais, pontos_de_atencao,
      tom_de_voz, palavras_chave, palavras_a_evitar, identidade_narrativa, orientacoes_de_imagem,
      prioridades_imediatas, metas_de_curto_prazo, metas_de_medio_prazo, observacoes_internas, status,
      created_by, updated_by)
    values (
      p_org, p_campaign_id, v_cy.id, v_cand.id,
      n_objele, n_objpol, n_posic, n_msg, n_slogan, n_narr, n_propval,
      p_publicos_prioritarios, p_segmentos_prioritarios, p_territorios_prioritarios, p_municipios_prioritarios, p_grupos_de_apoio, p_grupos_de_resistencia,
      p_temas_prioritarios, p_propostas_prioritarias, p_compromissos_publicos, p_bandeiras_centrais,
      n_fort, n_vuln, n_oport, n_amea, n_risco, n_aten,
      n_tom, p_palavras_chave, p_palavras_a_evitar, n_idnarr, n_orimg,
      p_prioridades_imediatas, p_metas_de_curto_prazo, p_metas_de_medio_prazo, n_obsest, v_status,
      v_uid, v_uid)
    returning id into v_sp_id;
    v_sp_novo := true;
  else
    v_sp_id := v_sp.id;
    v_sp_muda := (
         v_sp.objetivo_eleitoral is distinct from n_objele
      or v_sp.objetivo_politico is distinct from n_objpol
      or v_sp.posicionamento is distinct from n_posic
      or v_sp.mensagem_central is distinct from n_msg
      or v_sp.slogan is distinct from n_slogan
      or v_sp.narrativa_principal is distinct from n_narr
      or v_sp.proposta_de_valor is distinct from n_propval
      or v_sp.publicos_prioritarios is distinct from p_publicos_prioritarios
      or v_sp.segmentos_prioritarios is distinct from p_segmentos_prioritarios
      or v_sp.territorios_prioritarios is distinct from p_territorios_prioritarios
      or v_sp.municipios_prioritarios is distinct from p_municipios_prioritarios
      or v_sp.grupos_de_apoio is distinct from p_grupos_de_apoio
      or v_sp.grupos_de_resistencia is distinct from p_grupos_de_resistencia
      or v_sp.temas_prioritarios is distinct from p_temas_prioritarios
      or v_sp.propostas_prioritarias is distinct from p_propostas_prioritarias
      or v_sp.compromissos_publicos is distinct from p_compromissos_publicos
      or v_sp.bandeiras_centrais is distinct from p_bandeiras_centrais
      or v_sp.fortalezas is distinct from n_fort
      or v_sp.vulnerabilidades is distinct from n_vuln
      or v_sp.oportunidades is distinct from n_oport
      or v_sp.ameacas is distinct from n_amea
      or v_sp.riscos_reputacionais is distinct from n_risco
      or v_sp.pontos_de_atencao is distinct from n_aten
      or v_sp.tom_de_voz is distinct from n_tom
      or v_sp.palavras_chave is distinct from p_palavras_chave
      or v_sp.palavras_a_evitar is distinct from p_palavras_a_evitar
      or v_sp.identidade_narrativa is distinct from n_idnarr
      or v_sp.orientacoes_de_imagem is distinct from n_orimg
      or v_sp.prioridades_imediatas is distinct from p_prioridades_imediatas
      or v_sp.metas_de_curto_prazo is distinct from p_metas_de_curto_prazo
      or v_sp.metas_de_medio_prazo is distinct from p_metas_de_medio_prazo
      or v_sp.observacoes_internas is distinct from n_obsest
      or v_sp.status is distinct from v_status
    );
    if v_sp_muda then
      update public.campaign_strategy_profiles set
        objetivo_eleitoral=n_objele, objetivo_politico=n_objpol, posicionamento=n_posic,
        mensagem_central=n_msg, slogan=n_slogan, narrativa_principal=n_narr, proposta_de_valor=n_propval,
        publicos_prioritarios=p_publicos_prioritarios, segmentos_prioritarios=p_segmentos_prioritarios,
        territorios_prioritarios=p_territorios_prioritarios, municipios_prioritarios=p_municipios_prioritarios,
        grupos_de_apoio=p_grupos_de_apoio, grupos_de_resistencia=p_grupos_de_resistencia,
        temas_prioritarios=p_temas_prioritarios, propostas_prioritarias=p_propostas_prioritarias,
        compromissos_publicos=p_compromissos_publicos, bandeiras_centrais=p_bandeiras_centrais,
        fortalezas=n_fort, vulnerabilidades=n_vuln, oportunidades=n_oport, ameacas=n_amea,
        riscos_reputacionais=n_risco, pontos_de_atencao=n_aten, tom_de_voz=n_tom,
        palavras_chave=p_palavras_chave, palavras_a_evitar=p_palavras_a_evitar,
        identidade_narrativa=n_idnarr, orientacoes_de_imagem=n_orimg,
        prioridades_imediatas=p_prioridades_imediatas, metas_de_curto_prazo=p_metas_de_curto_prazo,
        metas_de_medio_prazo=p_metas_de_medio_prazo, observacoes_internas=n_obsest, status=v_status,
        updated_by=v_uid, updated_at=now()
      where id = v_sp_id;
    end if;
  end if;

  campaign_id              := p_campaign_id;
  candidate_id             := v_cand.id;
  candidacy_id             := v_cy.id;
  candidate_profile_id     := v_cp_id;
  strategy_profile_id      := v_sp_id;
  candidate_profile_criado := v_cp_novo;
  strategy_profile_criado  := v_sp_novo;
  ja_estava_atualizado     := (not v_cp_novo) and (not v_sp_novo)
                              and (v_cp_muda is not true) and (v_sp_muda is not true);
  return next;
end; $$;

revoke all on function public.save_campaign_candidate_profile(
  uuid,uuid,text,text,text,text,text,text,text,text,text,text,text,text,jsonb,jsonb,text,text,
  text,text,text,text,text,text,text,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,
  text,text,text,text,text,text,text,jsonb,jsonb,text,text,jsonb,jsonb,jsonb,text,text
) from public, anon;
grant execute on function public.save_campaign_candidate_profile(
  uuid,uuid,text,text,text,text,text,text,text,text,text,text,text,text,jsonb,jsonb,text,text,
  text,text,text,text,text,text,text,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,
  text,text,text,text,text,text,text,jsonb,jsonb,text,text,jsonb,jsonb,jsonb,text,text
) to authenticated;

-- ─────────────────────────────────────────────────────────────────────────
-- 6. Comentários.
-- ─────────────────────────────────────────────────────────────────────────
comment on table public.candidate_profiles is
'Identidade PERMANENTE do candidato (independe da eleição), isolada por organização. Um perfil ativo por (org_id, candidate_id). Não duplica dados eleitorais (ano/cargo/número/partido/UF/nome de urna), que pertencem a candidacies. Não armazena credenciais nem documentos sensíveis.';
comment on table public.campaign_strategy_profiles is
'ESTRATÉGIA de uma candidatura específica, isolada por organização e campanha. Um perfil ativo por campanha. Listas em JSONB (arrays de objetos). Distinto da identidade permanente do candidato: aqui ficam objetivo, mensagem, públicos, território, agenda, diagnóstico, comunicação e metas de UMA eleição.';
comment on column public.campaign_strategy_profiles.municipios_prioritarios is
'Array JSON. Ex.: [{"municipio":"Florianópolis","codigo_ibge":"4205407","prioridade":1,"objetivo":"ampliar reconhecimento"}].';
comment on column public.campaign_strategy_profiles.publicos_prioritarios is
'Array JSON. Ex.: [{"nome":"Jovens de 16 a 29 anos","prioridade":"alta","observacao":"Primeiro voto e universitários"}].';
comment on column public.campaign_strategy_profiles.temas_prioritarios is
'Array JSON. Ex.: [{"tema":"Educação","prioridade":"alta","posicionamento":"defesa da educação pública"}].';
comment on function public.save_campaign_candidate_profile(
  uuid,uuid,text,text,text,text,text,text,text,text,text,text,text,text,jsonb,jsonb,text,text,
  text,text,text,text,text,text,text,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,jsonb,
  text,text,text,text,text,text,text,jsonb,jsonb,text,text,jsonb,jsonb,jsonb,text,text
) is
'Upsert transacional do perfil permanente do candidato e do perfil estratégico da campanha. Só o proprietário da organização ou o admin da campanha pode executar. Deriva candidacy/candidate/membro principal de p_campaign_id (não confia em candidate_id do cliente), valida estrutura do Modelo C, UF base, status e JSONB. Idempotente: payload igual não gera UPDATE nem auditoria e retorna ja_estava_atualizado=true. Auditoria pelos triggers desta migration.';

COMMIT;

-- ============================================================================
-- TESTES MANUAIS (BEGIN/ROLLBACK; não executados). Placeholders <ORG>/<CAMPAIGN>.
-- Não usar a campanha real de Wilson Trevisan.
--  1.  não autenticado                        → 'Não autenticado.'
--  2.  não proprietário e não membro           → negado
--  3.  proprietário                             → salva
--  4.  admin da campanha                        → salva
--  5.  membro somente leitura                   → SELECT permitido; RPC nega escrita
--  6.  organização inexistente                  → 'Organização inexistente.'
--  7.  campanha inexistente                     → 'Campanha inexistente.'
--  8.  campanha de outra organização            → 'Campanha pertence a outra organização.'
--  9.  campanha arquivada                       → 'Campanha arquivada não pode receber perfil.'
--  10. campanha sem candidacy                   → 'requer correção estrutural'
--  11. múltiplas candidacies (impossível: UNIQUE campaign_id) — checar mesmo assim
--  12. candidatura sem principal                → 'requer correção estrutural'
--  13. múltiplos principais (impossível: índice) — checar mesmo assim
--  14. candidate inexistente                    → 'requer correção estrutural'
--  15. candidate de outra organização           → 'Inconsistência...'
--  16. criar os dois perfis                     → candidate_profile_criado/strategy_profile_criado = true
--  17. atualizar só candidate_profile           → strategy inalterado
--  18. atualizar só strategy_profile            → candidate inalterado
--  19. idempotência (mesmo payload)             → ja_estava_atualizado=true, sem auditoria
--  20. UF base 'sc'                             → normaliza para 'SC'
--  21. UF base 'SCC'                            → 'UF base inválida'
--  22. JSONB array válido em municipios_prioritarios → aceito
--  23. JSONB string em publicos_prioritarios    → 'deve ser array JSON'
--  24. status 'validado'                        → aceito
--  25. status 'xyz'                             → 'Status inválido'
--  26. isolamento entre organizações            → outra org não lê nem escreve
--  27. visualização por membro da campanha      → SELECT ok em strategy
--  28. escrita por admin                        → RPC salva
--  29. membro comum tentando RPC                → negado
--  30. auditoria                                → audit_log recebe INSERT/UPDATE das duas tabelas
--  31. concorrência (advisory lock)             → chamadas serializadas
--  32. rollback (erro no meio)                  → nada persistido
--  33. candidato com >1 candidatura             → candidate_profiles único por org; strategy por campanha
--  34. duas campanhas da mesma org              → dois strategy distintos, um candidate_profile
--  35. dados públicos                           → seguem acessíveis (RLS destas tabelas não os afeta)
--
-- Exemplo:
--   begin;
--     select * from public.save_campaign_candidate_profile(
--       '<CAMPAIGN>'::uuid, '<ORG>'::uuid,
--       'Nome Público', 'Bio curta', 'Bio completa', 'Profissão', 'Formação',
--       'Florianópolis','SC','Trajetória política','Trajetória profissional','Trajetória social',
--       'Causas','Realizações', '{"instagram":"@x"}'::jsonb, '{"whatsapp":"48..."}'::jsonb,
--       'https://exemplo/foto.jpg','Obs candidato',
--       'Objetivo eleitoral','Objetivo político','Posicionamento','Mensagem central','Slogan',
--       'Narrativa','Proposta de valor',
--       '[{"nome":"Jovens","prioridade":"alta"}]'::jsonb, '[]'::jsonb, '[]'::jsonb,
--       '[{"municipio":"Florianópolis","codigo_ibge":"4205407","prioridade":1}]'::jsonb,
--       '[]'::jsonb,'[]'::jsonb,'[{"tema":"Educação","prioridade":"alta"}]'::jsonb,
--       '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,
--       'Fortalezas','Vulnerabilidades','Oportunidades','Ameaças','Riscos','Atenção',
--       'Tom de voz','["educação"]'::jsonb,'["polêmica"]'::jsonb,'Identidade','Imagem',
--       '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,'Obs estratégia','em_construcao');
--   rollback;
-- ============================================================================
