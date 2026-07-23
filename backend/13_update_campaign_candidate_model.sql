-- ============================================================================
-- 13_update_campaign_candidate_model.sql — Atualização transacional de campanha
-- no Modelo C (campaigns legado + candidacies + candidate principal), eliminando
-- divergência entre as três tabelas. Equivalente de edição da migration 12.
--
-- Cria EXCLUSIVAMENTE public.update_campaign_candidate_model.
-- Não cria tabelas/índices/policies/triggers; não altera migrations 01–12,
-- campaigns nem o frontend. Não troca o candidate_id principal.
--
-- AUDITORIA: as três tabelas já são auditadas em UPDATE por triggers existentes
-- (trg_audita_campaigns — migration 03; trg_candidacies_audita e
-- trg_candidates_audita — migration 10). Portanto NÃO se insere auditoria manual
-- aqui: cada UPDATE real dispara o registro correspondente, sem duplicação; e,
-- quando o payload é idêntico, nenhum UPDATE ocorre e nada é auditado.
--
-- AUTORIZAÇÃO: SECURITY DEFINER; só o proprietário real (organizations.dono_id).
-- Idempotente: payload igual ⇒ nenhum UPDATE, ja_estava_atualizada=true.
-- ============================================================================
BEGIN;

create or replace function public.update_campaign_candidate_model(
  p_campaign_id    uuid,
  p_org            uuid,
  p_candidato_nome text,
  p_ano            smallint,
  p_cargo          text,
  p_nome_urna      text,
  p_uf             text,
  p_numero         text,
  p_partido        text,
  p_tipo_comercial text,
  p_valor_texto    text,
  p_situacao       text
)
returns table (
  campaign_id            uuid,
  candidate_id           uuid,
  candidacy_id           uuid,
  member_id              uuid,
  candidato_compartilhado boolean,
  ja_estava_atualizada    boolean
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid         uuid := auth.uid();
  v_dono        uuid;
  v_nome        text;
  v_cargo_norm  text;
  v_cargo_canon text;
  v_abrangencia text;
  v_uf          text;
  v_numero      text;
  v_partido     text;
  v_nome_urna   text;
  v_valor       text;
  v_c           record;   -- campaigns
  v_cy          record;   -- candidacies
  v_cm          record;   -- candidacy_members principal
  v_cand_row    record;   -- candidates principal
  v_n_cy        integer;
  v_n_prin      integer;
  v_assoc       integer;
  v_compart     boolean;
  v_need_camp   boolean;
  v_need_cy     boolean;
  v_need_cand   boolean;
begin
  -- 1. Autenticação e chave.
  if v_uid is null then raise exception 'Não autenticado.'; end if;
  if p_campaign_id is null then raise exception 'p_campaign_id é obrigatório.'; end if;

  -- 2. Serializa edições concorrentes da mesma campanha.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_campaign_id::text, 0));

  -- 3. Organização e autorização (proprietário real), com FOR UPDATE.
  if p_org is null then raise exception 'Organização não informada.'; end if;
  select o.dono_id into v_dono from public.organizations o where o.id = p_org for update;
  if not found then raise exception 'Organização inexistente.'; end if;
  if v_dono is null then raise exception 'Organização sem proprietário.'; end if;
  if v_dono is distinct from v_uid then
    raise exception 'Apenas o proprietário da organização pode editar a campanha.';
  end if;

  -- 4. Campanha (FOR UPDATE): existente, mesma org, não arquivada.
  select c.* into v_c from public.campaigns c where c.id = p_campaign_id for update;
  if not found then raise exception 'Campanha inexistente.'; end if;
  if v_c.org_id is distinct from p_org then
    raise exception 'Campanha pertence a outra organização.';
  end if;
  if v_c.archived_at is not null then
    raise exception 'Campanha arquivada não pode ser editada.';
  end if;

  -- 5. Validação e normalização (idênticas à migration 12).
  if p_ano is null or p_ano < 1990 or p_ano > 2100 then
    raise exception 'Ano inválido: % (esperado entre 1990 e 2100).', p_ano;
  end if;
  if coalesce(p_tipo_comercial, '') not in ('doada','vendida') then
    raise exception 'Tipo comercial inválido: "%".', p_tipo_comercial;
  end if;
  if coalesce(p_situacao, '') not in ('ativa','suspensa','expirada') then
    raise exception 'Situação inválida: "%".', p_situacao;
  end if;

  v_nome := btrim(coalesce(p_candidato_nome, ''));
  if v_nome = '' then raise exception 'Nome do candidato é obrigatório.'; end if;

  v_cargo_norm := lower(btrim(coalesce(p_cargo, '')));
  v_cargo_norm := regexp_replace(v_cargo_norm, '[ ./-]+', '_', 'g');
  v_cargo_norm := regexp_replace(v_cargo_norm, '_+', '_', 'g');
  v_cargo_norm := btrim(v_cargo_norm, '_');
  v_cargo_canon := case v_cargo_norm
    when 'presidente'          then 'presidente'
    when 'governador'          then 'governador'
    when 'senador'             then 'senador'
    when 'dep_federal'         then 'deputado_federal'
    when 'deputado_federal'    then 'deputado_federal'
    when 'dep_estadual'        then 'deputado_estadual'
    when 'deputado_estadual'   then 'deputado_estadual'
    when 'dep_distrital'       then 'deputado_distrital'
    when 'deputado_distrital'  then 'deputado_distrital'
    when 'prefeito'            then 'prefeito'
    when 'vereador'            then 'vereador'
    else null
  end;
  if v_cargo_canon is null then
    raise exception 'Cargo não reconhecido: "%". Informe um cargo canônico (presidente, governador, senador, deputado_federal, deputado_estadual, deputado_distrital, prefeito, vereador).', p_cargo;
  end if;

  v_abrangencia := case v_cargo_canon
    when 'presidente'         then 'nacional'
    when 'governador'         then 'estadual'
    when 'senador'            then 'estadual'
    when 'deputado_federal'   then 'estadual'
    when 'deputado_estadual'  then 'estadual'
    when 'deputado_distrital' then 'distrital'
    when 'prefeito'           then 'municipal'
    when 'vereador'           then 'municipal'
  end;

  if p_uf is null or btrim(p_uf) = '' then
    v_uf := null;
  else
    v_uf := upper(btrim(p_uf));
    if v_uf !~ '^[A-Z]{2}$' then raise exception 'UF inválida: "%".', p_uf; end if;
    if v_uf not in
      ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB',
       'PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO') then
      raise exception 'UF inválida: "%".', p_uf;
    end if;
  end if;
  if v_cargo_canon <> 'presidente' and v_uf is null then
    raise exception 'UF é obrigatória para o cargo %.', v_cargo_canon;
  end if;

  if p_numero is null or btrim(p_numero) = '' then
    v_numero := null;
  elsif btrim(p_numero) ~ '^[0-9]+$' then
    v_numero := btrim(p_numero);            -- preserva zeros à esquerda (texto)
  else
    raise exception 'Número inválido: "%" (apenas dígitos são aceitos).', p_numero;
  end if;

  v_partido   := upper(nullif(btrim(coalesce(p_partido, '')), ''));
  v_nome_urna := coalesce(nullif(btrim(coalesce(p_nome_urna, '')), ''), v_nome);
  v_valor     := nullif(btrim(coalesce(p_valor_texto, '')), '');

  -- 6. Estrutura do Modelo C (rejeita incompletude/inconsistência; sem reparo).
  select count(*) into v_n_cy from public.candidacies cy where cy.campaign_id = p_campaign_id;
  if v_n_cy = 0 then
    raise exception 'Campanha sem candidatura: requer correção estrutural (backfill).';
  elsif v_n_cy > 1 then
    raise exception 'Campanha com mais de uma candidatura: requer correção estrutural.';
  end if;
  select cy.* into v_cy from public.candidacies cy where cy.campaign_id = p_campaign_id for update;
  if v_cy.org_id is distinct from p_org then
    raise exception 'Inconsistência: candidatura de organização diferente da campanha.';
  end if;

  select count(*) into v_n_prin from public.candidacy_members cm
    where cm.candidacy_id = v_cy.id and cm.is_principal = true;
  if v_n_prin = 0 then
    raise exception 'Candidatura sem membro principal: requer correção estrutural.';
  elsif v_n_prin > 1 then
    raise exception 'Candidatura com mais de um membro principal: requer correção estrutural.';
  end if;
  select cm.* into v_cm from public.candidacy_members cm
    where cm.candidacy_id = v_cy.id and cm.is_principal = true for update;
  if v_cm.org_id is distinct from p_org then
    raise exception 'Inconsistência: composição de organização diferente.';
  end if;

  select cand.* into v_cand_row from public.candidates cand
    where cand.id = v_cm.candidate_id for update;
  if not found then
    raise exception 'Membro principal sem candidato: requer correção estrutural.';
  end if;
  if v_cand_row.org_id is distinct from p_org then
    raise exception 'Inconsistência: candidato de organização diferente.';
  end if;
  if v_cand_row.deleted_at is not null then
    raise exception 'Candidato principal está excluído: requer correção estrutural.';
  end if;

  -- 7. Candidato compartilhado? (nº de candidaturas que usam este candidate).
  select count(*) into v_assoc from public.candidacy_members cm where cm.candidate_id = v_cand_row.id;
  v_compart := v_assoc > 1;

  -- 8. O que mudou? (comparação com o payload normalizado)
  v_need_camp := (
       v_c.candidato_nome is distinct from v_nome
    or v_c.nome_urna      is distinct from v_nome_urna
    or v_c.cargo          is distinct from p_cargo        -- legado: valor recebido
    or v_c.uf             is distinct from v_uf
    or v_c.numero         is distinct from v_numero
    or v_c.partido        is distinct from v_partido
    or v_c.tipo_comercial is distinct from p_tipo_comercial
    or v_c.valor_texto    is distinct from v_valor
    or v_c.situacao       is distinct from p_situacao
  );
  v_need_cy := (
       v_cy.nome_urna             is distinct from v_nome_urna
    or v_cy.ano                   is distinct from p_ano
    or v_cy.cargo                 is distinct from v_cargo_canon
    or v_cy.abrangencia           is distinct from v_abrangencia
    or v_cy.uf                    is distinct from v_uf
    or v_cy.numero                is distinct from v_numero
    or v_cy.sigla_partido_disputa is distinct from v_partido
  );
  v_need_cand := (btrim(coalesce(v_cand_row.nome_cadastro, '')) is distinct from v_nome);

  -- 9. Nome de candidato compartilhado NÃO pode ser renomeado por aqui.
  if v_need_cand and v_compart then
    raise exception 'O candidato participa de mais de uma candidatura; renomeá-lo aqui alteraria a identidade em todas. Ajuste a identidade em fluxo próprio.';
  end if;

  -- 10. Idempotência: nada mudou ⇒ sem UPDATE, sem auditoria.
  if not (v_need_camp or v_need_cy or v_need_cand) then
    campaign_id             := p_campaign_id;
    candidate_id            := v_cand_row.id;
    candidacy_id            := v_cy.id;
    member_id               := v_cm.id;
    candidato_compartilhado := v_compart;
    ja_estava_atualizada    := true;
    return next;
    return;
  end if;

  -- 11. UPDATEs apenas do que mudou (cada UPDATE dispara sua própria auditoria).
  if v_need_camp then
    update public.campaigns
       set candidato_nome = v_nome,
           nome_urna      = v_nome_urna,
           cargo          = p_cargo,
           uf             = v_uf,
           numero         = v_numero,
           partido        = v_partido,
           tipo_comercial = p_tipo_comercial,
           valor_texto    = v_valor,
           situacao       = p_situacao
     where id = p_campaign_id;
  end if;

  if v_need_cy then
    update public.candidacies
       set nome_urna             = v_nome_urna,
           ano                   = p_ano,
           cargo                 = v_cargo_canon,
           abrangencia           = v_abrangencia,
           uf                    = v_uf,
           numero                = v_numero,
           sigla_partido_disputa = v_partido
     where id = v_cy.id;
  end if;

  if v_need_cand then
    update public.candidates set nome_cadastro = v_nome where id = v_cand_row.id;
  end if;

  campaign_id             := p_campaign_id;
  candidate_id            := v_cand_row.id;
  candidacy_id            := v_cy.id;
  member_id               := v_cm.id;
  candidato_compartilhado := v_compart;
  ja_estava_atualizada    := false;
  return next;
end;
$$;

comment on function public.update_campaign_candidate_model(
  uuid, uuid, text, smallint, text, text, text, text, text, text, text, text
) is
'Atualiza de forma coordenada e transacional campanha (campos legados de campaigns), candidatura (candidacies) e o nome do candidato principal (candidates), mantendo-os consistentes no Modelo C. Somente o proprietário real da organização (organizations.dono_id = auth.uid()) pode executar. Não troca o candidate_id principal; se o candidato participa de mais de uma candidatura (candidato_compartilhado=true), bloqueia a renomeação para não alterar a identidade em todas as campanhas. É idempotente: payload idêntico ao estado atual não gera UPDATE nem auditoria e retorna ja_estava_atualizada=true. Auditoria é feita pelos triggers existentes de UPDATE (migrations 03 e 10). Retorna campaign_id, candidate_id, candidacy_id, member_id, candidato_compartilhado, ja_estava_atualizada.';

revoke all on function public.update_campaign_candidate_model(
  uuid, uuid, text, smallint, text, text, text, text, text, text, text, text
) from public, anon;
grant execute on function public.update_campaign_candidate_model(
  uuid, uuid, text, smallint, text, text, text, text, text, text, text, text
) to authenticated;

COMMIT;

-- ============================================================================
-- TESTES MANUAIS (BEGIN/ROLLBACK; não executados aqui). UUIDs são placeholders:
--   <CAMPAIGN> <ORG> = campanha e organização reais do proprietário logado.
-- Executar autenticado como o proprietário, salvo os testes de negação.
--
--  1.  não autenticado (auth.uid() nulo)                         → 'Não autenticado.'
--  2.  autenticado, não proprietário                             → 'Apenas o proprietário...'
--  3.  p_org inexistente                                         → 'Organização inexistente.'
--  4.  p_campaign_id inexistente                                 → 'Campanha inexistente.'
--  5.  campanha de outra organização                             → 'Campanha pertence a outra organização.'
--  6.  campanha sem candidacy                                    → 'Campanha sem candidatura...'
--  7.  candidacy sem membro principal                            → 'Candidatura sem membro principal...'
--  8.  candidacy com dois principais                             → 'mais de um membro principal...'
--  9.  candidate de outra organização                            → 'Inconsistência: candidato de organização diferente.'
--  10. atualização apenas comercial (tipo/valor/situacao)        → só campaigns muda; ja_estava_atualizada=false
--  11. alteração de ano                                          → candidacies muda
--  12. alteração de cargo ("Dep. Federal"→deputado_federal)      → campaigns.cargo legado + candidacies.cargo canônico
--  13. alteração de UF                                           → campaigns.uf e candidacies.uf
--  14. alteração de número preservando zeros ('00123')           → número mantido como texto
--  15. alteração de partido                                      → upper aplicado
--  16. alteração de nome de urna                                 → ambas as tabelas
--  17. alteração do nome de candidate EXCLUSIVO (1 candidatura)  → candidates.nome_cadastro atualizado
--  18. alterar nome de candidate COMPARTILHADO (>1 candidatura)  → erro de bloqueio; candidato_compartilhado=true
--  19. repetição idempotente do mesmo payload                    → ja_estava_atualizada=true, sem auditoria nova
--  20. payload inválido (ano/UF/cargo/número)                    → erro específico, rollback
--  21. concorrência: duas chamadas simultâneas p/ mesma campanha → serializadas pelo advisory lock
--  22. auditoria: cada UPDATE real gera 1 registro (03/10); idempotente não gera
--  23. permissão: authenticated executa
--  24. negação: anon não possui EXECUTE
--  25. rollback: qualquer erro desfaz todos os UPDATEs sem resíduo
--
-- Exemplo (dentro de transação para inspeção, revertendo ao final):
--   begin;
--     select * from public.update_campaign_candidate_model(
--       '<CAMPAIGN>'::uuid, '<ORG>'::uuid, 'Nome do Candidato', 2026::smallint,
--       'Dep. Federal', 'Nome Urna', 'SC', '00123', 'PSD', 'doada', 'R$ 3.000', 'ativa');
--   rollback;
-- ============================================================================
