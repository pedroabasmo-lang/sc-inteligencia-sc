-- ============================================================================
-- 08_campaign_team_management.sql — Fundação segura da gestão de equipe.
--
-- Não altera o frontend. Não usa service_role. Toda administração de membros
-- passa a ocorrer por RPCs SECURITY DEFINER autorizadas EXCLUSIVAMENTE ao
-- proprietário real da organização da campanha (organizations.dono_id).
--
-- Identidade de usuário é resolvida SOMENTE por auth.users.email (normalizado
-- com lower(trim)). public.profiles.email NÃO é usado para identidade.
--
-- audit_log (estrutura existente, sem invenção de colunas):
--   id bigserial | campaign_id uuid | user_id uuid (quem executou) |
--   acao text | entidade text | entidade_id text (usuário afetado) |
--   antes jsonb (papel/escopo anterior) | depois jsonb (papel/escopo novo) |
--   criado_em timestamptz.
-- As três ações (MEMBER_ADD, MEMBER_ROLE_UPDATE, MEMBER_REMOVE) são
-- integralmente representáveis nessas colunas.
--
-- Executável de uma única vez (idempotente por drop/create-or-replace).
-- ============================================================================
BEGIN;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. POLICY p_campmem_ins: inserção direta serve APENAS ao vínculo inicial do
--    proprietário no ato de criação da campanha. Exige simultaneamente que a
--    linha seja a do próprio usuário (user_id = auth.uid()) E que a campanha
--    pertença a organização cujo dono é o mesmo usuário. Todos os DEMAIS
--    membros só entram pela RPC add_campaign_member_by_email (SECURITY DEFINER).
-- ─────────────────────────────────────────────────────────────────────────
drop policy if exists p_campmem_ins on public.campaign_members;
create policy p_campmem_ins on public.campaign_members for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and campaign_id in (
      select c.id
        from public.campaigns c
        join public.organizations o on o.id = c.org_id
       where o.dono_id = (select auth.uid())
    )
  );

-- 1b. Remover a policy direta de DELETE. Remoção passa a ocorrer somente por
--     remove_campaign_member (SECURITY DEFINER + auditoria MEMBER_REMOVE).
--     NÃO recriar policy direta de DELETE nem de UPDATE em campaign_members.
drop policy if exists p_campmem_del on public.campaign_members;

-- ─────────────────────────────────────────────────────────────────────────
-- 2. RPC: list_campaign_team(p_campaign)
--    Retorna o proprietário (mesmo sem linha em campaign_members) + membros,
--    com e-mail verdadeiro de auth.users.
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.list_campaign_team(p_campaign uuid)
returns table (
  user_id   uuid,
  nome      text,
  email     text,
  papel     text,
  escopo    text,
  criado_em timestamptz,
  is_owner  boolean
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_uid  uuid := auth.uid();
  v_org  uuid;
  v_dono uuid;
begin
  if v_uid is null then
    raise exception 'Não autenticado.';
  end if;

  select c.org_id into v_org from public.campaigns c where c.id = p_campaign;
  if v_org is null then
    raise exception 'Campanha não encontrada.';
  end if;

  select o.dono_id into v_dono from public.organizations o where o.id = v_org;
  if v_dono is distinct from v_uid then
    raise exception 'Apenas o proprietário da organização pode administrar a equipe.';
  end if;

  return query
    -- proprietário (papel sintético 'proprietario'; sem linha em campaign_members)
    select v_dono,
           p.nome,
           u.email::text,
           'proprietario'::text,
           null::text,
           null::timestamptz,
           true
      from public.profiles p
      join auth.users u on u.id = v_dono
     where p.id = v_dono
    union all
    -- demais membros
    select cm.user_id,
           p.nome,
           u.email::text,
           cm.papel,
           cm.escopo,
           cm.criado_em,
           false
      from public.campaign_members cm
      join public.profiles p on p.id = cm.user_id
      join auth.users     u on u.id = cm.user_id
     where cm.campaign_id = p_campaign
       and cm.user_id <> v_dono;
end;
$$;

-- ─────────────────────────────────────────────────────────────────────────
-- 3. RPC: add_campaign_member_by_email(p_campaign, p_email, p_papel, p_escopo)
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.add_campaign_member_by_email(
  p_campaign uuid,
  p_email    text,
  p_papel    text,
  p_escopo   text default null
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid    uuid := auth.uid();
  v_org    uuid;
  v_dono   uuid;
  v_email  text := lower(btrim(p_email));
  v_target uuid;
  v_n      integer;
  v_rows   integer;
begin
  if v_uid is null then
    raise exception 'Não autenticado.';
  end if;

  if p_papel is null or p_papel not in (
    'admin','candidato','coord_geral','coord_regional','coord_municipal',
    'mobilizacao','financeiro','contabilidade','juridico','comunicacao',
    'fiscalizacao','consulta'
  ) then
    raise exception 'Papel inválido.';
  end if;

  if v_email is null or v_email = '' then
    raise exception 'E-mail obrigatório.';
  end if;

  select c.org_id into v_org from public.campaigns c where c.id = p_campaign;
  if v_org is null then
    raise exception 'Campanha não encontrada.';
  end if;

  select o.dono_id into v_dono from public.organizations o where o.id = v_org;
  if v_dono is distinct from v_uid then
    raise exception 'Apenas o proprietário da organização pode administrar a equipe.';
  end if;

  -- Identidade SOMENTE por auth.users.email (normalizado).
  select count(*) into v_n from auth.users u where lower(btrim(u.email)) = v_email;
  if v_n = 0 then
    raise exception 'Nenhum usuário cadastrado com o e-mail informado.';
  elsif v_n > 1 then
    raise exception 'Mais de um usuário com o mesmo e-mail; resolução manual necessária.';
  end if;

  select u.id into v_target from auth.users u where lower(btrim(u.email)) = v_email;

  -- Confirmar perfil público válido explicitamente (não depender de erro de FK).
  if not exists (select 1 from public.profiles where id = v_target) then
    raise exception 'A conta encontrada não possui perfil público válido.';
  end if;

  if v_target = v_dono then
    raise exception 'O proprietário não pode ser adicionado como membro.';
  end if;

  if exists (
    select 1 from public.campaign_members cm
     where cm.campaign_id = p_campaign and cm.user_id = v_target
  ) then
    raise exception 'Usuário já é membro desta campanha.';
  end if;

  insert into public.campaign_members (campaign_id, user_id, papel, escopo)
  values (p_campaign, v_target, p_papel, p_escopo);
  get diagnostics v_rows = row_count;
  if v_rows <> 1 then
    raise exception 'Falha ao adicionar membro (nenhuma linha afetada).';
  end if;

  insert into public.audit_log
    (campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values
    (p_campaign, v_uid, 'MEMBER_ADD', 'campaign_members', v_target::text,
     null,
     jsonb_build_object('papel', p_papel, 'escopo', p_escopo));

  return v_target;
end;
$$;

-- ─────────────────────────────────────────────────────────────────────────
-- 4. RPC: update_campaign_member_role(p_campaign, p_user, p_papel, p_escopo)
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.update_campaign_member_role(
  p_campaign uuid,
  p_user     uuid,
  p_papel    text,
  p_escopo   text default null
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid       uuid := auth.uid();
  v_org       uuid;
  v_dono      uuid;
  v_old_papel text;
  v_old_esc   text;
  v_rows      integer;
begin
  if v_uid is null then
    raise exception 'Não autenticado.';
  end if;

  if p_papel is null or p_papel not in (
    'admin','candidato','coord_geral','coord_regional','coord_municipal',
    'mobilizacao','financeiro','contabilidade','juridico','comunicacao',
    'fiscalizacao','consulta'
  ) then
    raise exception 'Papel inválido.';
  end if;

  select c.org_id into v_org from public.campaigns c where c.id = p_campaign;
  if v_org is null then
    raise exception 'Campanha não encontrada.';
  end if;

  select o.dono_id into v_dono from public.organizations o where o.id = v_org;
  if v_dono is distinct from v_uid then
    raise exception 'Apenas o proprietário da organização pode administrar a equipe.';
  end if;

  if p_user = v_dono then
    raise exception 'O proprietário não pode ter o papel alterado.';
  end if;

  -- Trava a linha (FOR UPDATE) para distinguir inexistência de valor nulo e
  -- impedir alteração concorrente entre a leitura do estado anterior e o UPDATE.
  select cm.papel, cm.escopo into v_old_papel, v_old_esc
    from public.campaign_members cm
   where cm.campaign_id = p_campaign and cm.user_id = p_user
   for update;
  if not found then
    raise exception 'Usuário não é membro desta campanha.';
  end if;

  update public.campaign_members cm
     set papel  = p_papel,
         escopo = p_escopo
   where cm.campaign_id = p_campaign
     and cm.user_id = p_user;
  get diagnostics v_rows = row_count;
  if v_rows <> 1 then
    raise exception 'Falha ao atualizar papel (nenhuma linha afetada).';
  end if;

  insert into public.audit_log
    (campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values
    (p_campaign, v_uid, 'MEMBER_ROLE_UPDATE', 'campaign_members', p_user::text,
     jsonb_build_object('papel', v_old_papel, 'escopo', v_old_esc),
     jsonb_build_object('papel', p_papel,     'escopo', p_escopo));
end;
$$;

-- ─────────────────────────────────────────────────────────────────────────
-- 5. RPC: remove_campaign_member(p_campaign, p_user)
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.remove_campaign_member(
  p_campaign uuid,
  p_user     uuid
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid       uuid := auth.uid();
  v_org       uuid;
  v_dono      uuid;
  v_old_papel text;
  v_old_esc   text;
  v_rows      integer;
begin
  if v_uid is null then
    raise exception 'Não autenticado.';
  end if;

  select c.org_id into v_org from public.campaigns c where c.id = p_campaign;
  if v_org is null then
    raise exception 'Campanha não encontrada.';
  end if;

  select o.dono_id into v_dono from public.organizations o where o.id = v_org;
  if v_dono is distinct from v_uid then
    raise exception 'Apenas o proprietário da organização pode administrar a equipe.';
  end if;

  if p_user = v_dono then
    raise exception 'O proprietário não pode ser removido.';
  end if;

  delete from public.campaign_members cm
   where cm.campaign_id = p_campaign
     and cm.user_id = p_user
  returning cm.papel, cm.escopo into v_old_papel, v_old_esc;
  get diagnostics v_rows = row_count;
  if v_rows <> 1 then
    raise exception 'Membro não encontrado nesta campanha.';
  end if;

  insert into public.audit_log
    (campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values
    (p_campaign, v_uid, 'MEMBER_REMOVE', 'campaign_members', p_user::text,
     jsonb_build_object('papel', v_old_papel, 'escopo', v_old_esc),
     null);
end;
$$;

-- ─────────────────────────────────────────────────────────────────────────
-- 6. Privilégios: nenhuma execução por PUBLIC/anon; somente authenticated.
-- ─────────────────────────────────────────────────────────────────────────
revoke execute on function public.list_campaign_team(uuid)                        from public, anon;
revoke execute on function public.add_campaign_member_by_email(uuid, text, text, text) from public, anon;
revoke execute on function public.update_campaign_member_role(uuid, uuid, text, text)  from public, anon;
revoke execute on function public.remove_campaign_member(uuid, uuid)              from public, anon;

grant execute on function public.list_campaign_team(uuid)                         to authenticated;
grant execute on function public.add_campaign_member_by_email(uuid, text, text, text)  to authenticated;
grant execute on function public.update_campaign_member_role(uuid, uuid, text, text)   to authenticated;
grant execute on function public.remove_campaign_member(uuid, uuid)               to authenticated;

COMMIT;
