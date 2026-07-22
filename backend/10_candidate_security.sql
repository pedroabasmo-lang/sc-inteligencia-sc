-- ============================================================================
-- 10_candidate_security.sql — Camada de segurança e governança do núcleo de
-- candidatos (candidates, candidacies, candidacy_members) criado na 09.
--
-- Pressupõe que a 09 foi executada imediatamente antes. Cria: funções de
-- autorização, triggers de proteção estrutural, autoria/timestamps, auditoria
-- (reutilizando public.audit_log), policies RLS e grants mínimos a authenticated.
--
-- NÃO cria: backfill, views, RPCs de transição, alteração de campos legados de
-- campaigns, candidate_private_profiles, candidate_party_history, estratégia,
-- documentos, financeiro, jurídico, contratos, vínculo candidato-usuário por
-- aceite, nem qualquer acesso a anon. DELETE direto permanece proibido.
--
-- Decisão de autorização: NÃO se reutiliza public.is_org_owner (migration 02),
-- pois ela concede acesso também a organization_members com papel_org admin.
-- O comando exige que a escrita seja restrita ao PROPRIETÁRIO REAL da
-- organização (organizations.dono_id). Cria-se, portanto, public.is_org_dono.
--
-- Padrão herdado das migrations 07/08: SECURITY DEFINER + SET search_path = '',
-- objetos totalmente qualificados, REVOKE de public/anon, EXECUTE só a
-- authenticated quando necessário para a RLS.
-- ============================================================================
BEGIN;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Funções de autorização (SECURITY DEFINER interrompem recursão de RLS:
--    consultam as tabelas como dono, sem reativar as policies destas tabelas).
-- ─────────────────────────────────────────────────────────────────────────

-- Proprietário REAL da organização (somente organizations.dono_id).
create or replace function public.is_org_dono(p_org_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.organizations o
     where o.id = p_org_id and o.dono_id = (select auth.uid())
  );
$$;

-- Leitura de candidato: proprietário da org OU membro de campanha vinculada
-- ao candidato via candidacy_members → candidacies (com campaign_id).
create or replace function public.can_read_candidate(p_candidate_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.candidates cand
     where cand.id = p_candidate_id and public.is_org_dono(cand.org_id)
  ) or exists (
    select 1
      from public.candidates cand
      join public.candidacy_members cm on cm.candidate_id = cand.id
      join public.candidacies c        on c.id = cm.candidacy_id
      join public.campaign_members m   on m.campaign_id = c.campaign_id
     where cand.id = p_candidate_id
       and cand.deleted_at is null
       and c.campaign_id is not null
       and m.user_id = (select auth.uid())
  );
$$;

-- Leitura de candidatura (e, por extensão, de sua composição): proprietário
-- da org OU membro da campanha vinculada. Sem campaign_id → só o proprietário.
create or replace function public.can_read_candidacy(p_candidacy_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.candidacies c
     where c.id = p_candidacy_id and public.is_org_dono(c.org_id)
  ) or exists (
    select 1
      from public.candidacies c
      join public.campaign_members m on m.campaign_id = c.campaign_id
     where c.id = p_candidacy_id
       and c.campaign_id is not null
       and m.user_id = (select auth.uid())
  );
$$;

revoke all on function public.is_org_dono(uuid)        from public, anon;
revoke all on function public.can_read_candidate(uuid) from public, anon;
revoke all on function public.can_read_candidacy(uuid) from public, anon;
grant execute on function public.is_org_dono(uuid)        to authenticated;
grant execute on function public.can_read_candidate(uuid) to authenticated;
grant execute on function public.can_read_candidacy(uuid) to authenticated;

-- ─────────────────────────────────────────────────────────────────────────
-- 2. Proteção de campos estruturais imutáveis (BEFORE UPDATE, SECURITY INVOKER:
--    comparação NEW×OLD não exige privilégio elevado). Erro claro, sem correção
--    silenciosa e sem variável de sessão controlável pelo cliente.
--
--    Compatibilidade com ON DELETE SET NULL (migration 09): as FKs user_id/
--    criado_por/atualizado_por usam SET NULL; a limpeza referencial é executada
--    pelo PostgreSQL como UPDATE interno na tabela dependente, disparando estes
--    triggers BEFORE UPDATE. Distinção:
--      - pg_trigger_depth() = 1  → UPDATE direto normal (cliente/sistema);
--      - pg_trigger_depth() > 1  → UPDATE provocado por ação referencial interna.
--    A exceção liberada abaixo permite APENAS a transição de UUID não nulo para
--    NULL feita internamente pela FK; nunca troca de identidade (UUID→UUID) nem
--    definição de NULL diretamente pelo cliente.
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.protege_candidates_estrutura()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.id        is distinct from old.id
  or new.org_id    is distinct from old.org_id
  or new.criado_em is distinct from old.criado_em then
    raise exception 'Campos estruturais de candidates (id, org_id, criado_em) não podem ser alterados.';
  end if;
  if new.user_id is distinct from old.user_id
  and not (pg_trigger_depth() > 1 and old.user_id is not null and new.user_id is null) then
    raise exception 'candidates.user_id não pode ser alterado por edição direta (vínculo futuro por RPC com aceite).';
  end if;
  if new.criado_por is distinct from old.criado_por
  and not (pg_trigger_depth() > 1 and old.criado_por is not null and new.criado_por is null) then
    raise exception 'candidates.criado_por não pode ser alterado por edição direta.';
  end if;
  return new;
end;
$$;

create or replace function public.protege_candidacies_estrutura()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.id          is distinct from old.id
  or new.org_id      is distinct from old.org_id
  or new.campaign_id is distinct from old.campaign_id
  or new.criado_em   is distinct from old.criado_em then
    raise exception 'Campos estruturais de candidacies (id, org_id, campaign_id, criado_em) não podem ser alterados por edição direta.';
  end if;
  -- campaign_id acima permanece absolutamente protegido (FK ON DELETE RESTRICT).
  if new.criado_por is distinct from old.criado_por
  and not (pg_trigger_depth() > 1 and old.criado_por is not null and new.criado_por is null) then
    raise exception 'candidacies.criado_por não pode ser alterado por edição direta.';
  end if;
  return new;
end;
$$;

create or replace function public.protege_candidacy_members_estrutura()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.id           is distinct from old.id
  or new.org_id       is distinct from old.org_id
  or new.candidacy_id is distinct from old.candidacy_id
  or new.candidate_id is distinct from old.candidate_id
  or new.criado_em    is distinct from old.criado_em then
    raise exception 'Campos estruturais de candidacy_members (id, org_id, candidacy_id, candidate_id, criado_em) não podem ser alterados por edição direta.';
  end if;
  if new.criado_por is distinct from old.criado_por
  and not (pg_trigger_depth() > 1 and old.criado_por is not null and new.criado_por is null) then
    raise exception 'candidacy_members.criado_por não pode ser alterado por edição direta.';
  end if;
  return new;
end;
$$;

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Autoria e timestamps (não confia em valores enviados pelo cliente;
--    permite autoria nula quando auth.uid() é nulo, p/ backfill futuro).
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.set_autoria_candidato()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    new.criado_por     := auth.uid();
    new.criado_em      := now();
    new.atualizado_por := auth.uid();
    new.atualizado_em  := now();
  elsif tg_op = 'UPDATE' then
    -- Limpeza referencial interna (ON DELETE SET NULL, pg_trigger_depth() > 1) NÃO
    -- deve repopular atualizado_por/atualizado_em: o NULL definido pela FK é
    -- preservado e apenas o trigger de auditoria registra a mudança técnica.
    if pg_trigger_depth() > 1 then
      return new;
    end if;
    -- criado_por/criado_em são preservados pela proteção estrutural (que roda antes);
    -- aqui apenas registra a atualização direta normal.
    new.atualizado_por := auth.uid();
    new.atualizado_em  := now();
  end if;
  return new;
end;
$$;

create or replace function public.set_autoria_candidacy_member()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.criado_por := auth.uid();
  new.criado_em  := now();
  return new;
end;
$$;

-- ─────────────────────────────────────────────────────────────────────────
-- 4. Auditoria reutilizando public.audit_log (mesmo formato das migrations 03/07).
--    audit_log não tem coluna de organização; campaign_id fica nulo quando a
--    entidade não tem campanha associada. Sem alterar o schema de audit_log.
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.audita_candidates()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (
    null, auth.uid(), tg_op, 'candidates', new.id::text,
    case when tg_op = 'UPDATE' then to_jsonb(old) else null end,
    to_jsonb(new)
  );
  return null;
end;
$$;

create or replace function public.audita_candidacies()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (
    new.campaign_id, auth.uid(), tg_op, 'candidacies', new.id::text,
    case when tg_op = 'UPDATE' then to_jsonb(old) else null end,
    to_jsonb(new)
  );
  return null;
end;
$$;

create or replace function public.audita_candidacy_members()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_campaign uuid;
begin
  select c.campaign_id into v_campaign
    from public.candidacies c
   where c.id = new.candidacy_id;
  insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (
    v_campaign, auth.uid(), tg_op, 'candidacy_members', new.id::text,
    case when tg_op = 'UPDATE' then to_jsonb(old) else null end,
    to_jsonb(new)
  );
  return null;
end;
$$;

-- Privilégios das funções de trigger: nunca executáveis por public/anon.
revoke all on function public.protege_candidates_estrutura()        from public, anon;
revoke all on function public.protege_candidacies_estrutura()       from public, anon;
revoke all on function public.protege_candidacy_members_estrutura() from public, anon;
revoke all on function public.set_autoria_candidato()               from public, anon;
revoke all on function public.set_autoria_candidacy_member()        from public, anon;
revoke all on function public.audita_candidates()                   from public, anon;
revoke all on function public.audita_candidacies()                  from public, anon;
revoke all on function public.audita_candidacy_members()            from public, anon;

-- ─────────────────────────────────────────────────────────────────────────
-- 5. Triggers. Nomes ordenam a execução BEFORE UPDATE: 'protege_' (p) antes de
--    'set_autoria_' (s), garantindo que a proteção veja os valores do cliente
--    e lance erro em vez de a autoria corrigir silenciosamente.
-- ─────────────────────────────────────────────────────────────────────────
create trigger trg_candidates_protege_estrutura
  before update on public.candidates
  for each row execute function public.protege_candidates_estrutura();
create trigger trg_candidates_set_autoria
  before insert or update on public.candidates
  for each row execute function public.set_autoria_candidato();
create trigger trg_candidates_audita
  after insert or update on public.candidates
  for each row execute function public.audita_candidates();

create trigger trg_candidacies_protege_estrutura
  before update on public.candidacies
  for each row execute function public.protege_candidacies_estrutura();
create trigger trg_candidacies_set_autoria
  before insert or update on public.candidacies
  for each row execute function public.set_autoria_candidato();
create trigger trg_candidacies_audita
  after insert or update on public.candidacies
  for each row execute function public.audita_candidacies();

create trigger trg_candmembers_protege_estrutura
  before update on public.candidacy_members
  for each row execute function public.protege_candidacy_members_estrutura();
create trigger trg_candmembers_set_autoria
  before insert on public.candidacy_members
  for each row execute function public.set_autoria_candidacy_member();
create trigger trg_candmembers_audita
  after insert or update on public.candidacy_members
  for each row execute function public.audita_candidacy_members();

-- ─────────────────────────────────────────────────────────────────────────
-- 6. Policies (RLS já habilitada na 09). SELECT/INSERT/UPDATE; sem DELETE.
--    Escrita exclusiva do proprietário real da organização.
-- ─────────────────────────────────────────────────────────────────────────

-- candidates
create policy p_candidates_sel on public.candidates for select to authenticated
  using (public.is_org_dono(org_id) or public.can_read_candidate(id));
create policy p_candidates_ins on public.candidates for insert to authenticated
  with check (public.is_org_dono(org_id) and user_id is null and deleted_at is null);
create policy p_candidates_upd on public.candidates for update to authenticated
  using (public.is_org_dono(org_id))
  with check (public.is_org_dono(org_id));

-- candidacies
create policy p_candidacies_sel on public.candidacies for select to authenticated
  using (public.is_org_dono(org_id) or public.can_read_candidacy(id));
create policy p_candidacies_ins on public.candidacies for insert to authenticated
  with check (public.is_org_dono(org_id) and campaign_id is null);
create policy p_candidacies_upd on public.candidacies for update to authenticated
  using (public.is_org_dono(org_id))
  with check (public.is_org_dono(org_id));

-- candidacy_members
create policy p_candmembers_sel on public.candidacy_members for select to authenticated
  using (public.is_org_dono(org_id) or public.can_read_candidacy(candidacy_id));
create policy p_candmembers_ins on public.candidacy_members for insert to authenticated
  with check (public.is_org_dono(org_id));
create policy p_candmembers_upd on public.candidacy_members for update to authenticated
  using (public.is_org_dono(org_id))
  with check (public.is_org_dono(org_id));

-- ─────────────────────────────────────────────────────────────────────────
-- 7. Privilégios POR COLUNA (barreira primária de imutabilidade; os triggers de
--    proteção são a segunda camada). SELECT no nível da tabela; INSERT/UPDATE
--    apenas nas colunas que o proprietário pode fornecer. RLS continua sendo a
--    autorização de LINHA efetiva. Sem DELETE, TRUNCATE, REFERENCES, TRIGGER;
--    sem anon; sem PUBLIC.
--    Colunas de identidade/autoria/estrutura (id, org_id, user_id, campaign_id,
--    candidacy_id, candidate_id, criado_por, criado_em, atualizado_por,
--    atualizado_em, deleted_at no INSERT) ficam fora dos grants e são controladas
--    por default, trigger, policy ou RPC futura.
-- ─────────────────────────────────────────────────────────────────────────
revoke all on public.candidates        from public, anon, authenticated;
revoke all on public.candidacies       from public, anon, authenticated;
revoke all on public.candidacy_members from public, anon, authenticated;

-- SELECT: tabela completa (a RLS decide as linhas).
grant select on public.candidates        to authenticated;
grant select on public.candidacies       to authenticated;
grant select on public.candidacy_members to authenticated;

-- candidates: INSERT
grant insert (
  org_id,
  nome_cadastro,
  nome_civil,
  identidade_confirmada,
  nome_politico,
  nome_urna_preferencial,
  biografia_publica,
  profissao,
  formacao_publica,
  site,
  redes_publicas,
  foto_path
) on public.candidates to authenticated;

-- candidates: UPDATE
grant update (
  nome_cadastro,
  nome_civil,
  identidade_confirmada,
  nome_politico,
  nome_urna_preferencial,
  biografia_publica,
  profissao,
  formacao_publica,
  site,
  redes_publicas,
  foto_path,
  deleted_at
) on public.candidates to authenticated;

-- candidacies: INSERT (campaign_id fora dos grants; policy exige campaign_id IS NULL)
grant insert (
  org_id,
  nome_urna,
  ano,
  turno,
  cargo,
  uf,
  municipio_ibge,
  abrangencia,
  numero,
  sigla_partido_disputa,
  federacao_coligacao,
  sequencial_tse,
  fase,
  status_registro,
  status_recurso,
  resultado_eleitoral,
  situacao_mandato,
  votacao_obtida
) on public.candidacies to authenticated;

-- candidacies: UPDATE
grant update (
  nome_urna,
  ano,
  turno,
  cargo,
  uf,
  municipio_ibge,
  abrangencia,
  numero,
  sigla_partido_disputa,
  federacao_coligacao,
  sequencial_tse,
  fase,
  status_registro,
  status_recurso,
  resultado_eleitoral,
  situacao_mandato,
  votacao_obtida
) on public.candidacies to authenticated;

-- candidacy_members: INSERT
grant insert (
  org_id,
  candidacy_id,
  candidate_id,
  papel,
  ordem,
  is_principal
) on public.candidacy_members to authenticated;

-- candidacy_members: UPDATE
grant update (
  papel,
  ordem,
  is_principal
) on public.candidacy_members to authenticated;

COMMIT;

-- ============================================================================
-- TESTES A EXECUTAR APÓS APLICAR 09 E 10 (não executados aqui):
--  1.  anon não lê nenhuma das três tabelas.
--  2.  usuário autenticado sem campanha não lê nenhum candidato.
--  3.  perfil 'consulta' lê candidato vinculado à própria campanha.
--  4.  'consulta' não lê candidato de outra campanha.
--  5.  'mobilizacao' lê dados públicos do candidato/candidatura vinculados.
--  6.  qualquer membro de campanha (não dono) recebe negação em INSERT/UPDATE.
--  7.  proprietário da organização insere e atualiza candidato/candidatura/membro.
--  8.  proprietário não consegue alterar org_id (erro do trigger de proteção).
--  9.  proprietário não consegue alterar user_id diretamente (erro do trigger).
--  10. proprietário não consegue alterar campaign_id diretamente (erro do trigger).
--  11. DELETE é negado nas três tabelas (sem policy e sem grant).
--  12. criado_por/criado_em/atualizado_por/atualizado_em são preenchidos por trigger.
--  13. audit_log registra INSERT e UPDATE das três entidades.
--  14. candidatura sem campaign_id só é visível ao proprietário da organização.
--  15. vínculo entre organizações diferentes é rejeitado pelas FKs compostas (09).
--  16. proprietário NÃO cria candidacy com campaign_id preenchido por INSERT direto
--      (a ligação será feita futuramente por RPC transacional).
--  17. candidatura sem campaign_id gera auditoria sem erro (new.campaign_id nulo).
--  18. candidato com deleted_at não é visível para 'consulta' nem 'mobilizacao'.
--  19. candidato com deleted_at continua visível para o proprietário da organização.
--  20. audit_log recebe 'antes' somente no UPDATE; nulo no INSERT.
--  21. audit_log recebe 'depois' no INSERT e no UPDATE.
--  22. excluir profile vinculado a candidates.user_id define user_id como NULL (FK).
--  23. excluir profile usado em criado_por define criado_por como NULL nas 3 tabelas.
--  24. excluir profile usado em atualizado_por define atualizado_por como NULL.
--  25. a limpeza automática por FK (pg_trigger_depth() > 1) não é bloqueada.
--  26. proprietário NÃO consegue definir user_id como NULL diretamente.
--  27. proprietário NÃO consegue definir criado_por como NULL diretamente.
--  28. proprietário NÃO consegue trocar user_id ou criado_por por outro UUID.
--  29. auditoria registra o UPDATE técnico provocado pela FK (SET NULL).
--  30. UPDATE direto de candidates.user_id é negado por privilégio de coluna.
--  31. UPDATE direto de candidates.criado_por é negado por privilégio de coluna.
--  32. UPDATE direto de candidacies.campaign_id é negado por privilégio de coluna.
--  33. UPDATE direto de candidacy_members.candidate_id é negado por privilégio de coluna.
--  34. proprietário atualiza normalmente apenas os campos permitidos.
--  35. triggers continuam preenchendo atualizado_por e atualizado_em.
--  36. ON DELETE SET NULL continua funcionando apesar dos privilégios limitados.
--  37. RLS continua restringindo as linhas mesmo nas colunas permitidas.
-- ============================================================================
