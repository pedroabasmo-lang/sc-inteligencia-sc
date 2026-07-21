-- ============================================================================
-- Patch RLS — corrige "new row violates row-level security policy".
-- Recria as funções de segurança com search_path fixo e (select auth.uid()),
-- e reescreve as policies de campaigns/membros/supporters de forma direta.
-- Rodar no SQL Editor do Supabase (SQL/new). Idempotente.
-- ============================================================================

-- 1. Funções auxiliares robustas (search_path fixo, auth.uid via subselect)
create or replace function is_org_owner(p_org uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from organizations o
     where o.id = p_org and o.dono_id = (select auth.uid())
    union
    select 1 from organization_members m
     where m.org_id = p_org and m.user_id = (select auth.uid())
       and m.papel_org in ('dono','admin')
  );
$$;

create or replace function is_campaign_member(p_campaign uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from campaign_members cm
     where cm.campaign_id = p_campaign and cm.user_id = (select auth.uid())
  ) or exists (
    select 1 from campaigns c
     where c.id = p_campaign and is_org_owner(c.org_id)
  );
$$;

create or replace function campaign_role(p_campaign uuid) returns text
language sql stable security definer set search_path = public as $$
  select coalesce(
    (select papel from campaign_members
      where campaign_id = p_campaign and user_id = (select auth.uid()) limit 1),
    (select 'admin' from campaigns c
      where c.id = p_campaign and is_org_owner(c.org_id) limit 1)
  );
$$;

create or replace function campaign_ativa(p_campaign uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from campaigns c
     where c.id = p_campaign and c.situacao = 'ativa'
       and (c.expira_em is null or c.expira_em >= current_date)
  );
$$;

create or replace function can_read_supporters(p_campaign uuid) returns boolean
language sql stable set search_path = public as $$
  select campaign_role(p_campaign) in
    ('admin','candidato','coord_geral','coord_regional','coord_municipal','mobilizacao','consulta');
$$;
create or replace function can_write_supporters(p_campaign uuid) returns boolean
language sql stable set search_path = public as $$
  select campaign_role(p_campaign) in ('admin','coord_geral','coord_municipal','mobilizacao');
$$;

-- 2. Organizations — policies diretas
drop policy if exists p_org_sel on organizations;
drop policy if exists p_org_ins on organizations;
drop policy if exists p_org_upd on organizations;
create policy p_org_sel on organizations for select to authenticated
  using (dono_id = (select auth.uid()) or is_org_owner(id));
create policy p_org_ins on organizations for insert to authenticated
  with check (dono_id = (select auth.uid()));
create policy p_org_upd on organizations for update to authenticated
  using (dono_id = (select auth.uid()));

-- 3. Campaigns — insert/update/delete diretos (não dependem de função)
drop policy if exists p_camp_sel on campaigns;
drop policy if exists p_camp_ins on campaigns;
drop policy if exists p_camp_upd on campaigns;
drop policy if exists p_camp_del on campaigns;
create policy p_camp_sel on campaigns for select to authenticated
  using (is_campaign_member(id));
create policy p_camp_ins on campaigns for insert to authenticated
  with check (org_id in (select id from organizations where dono_id = (select auth.uid())));
create policy p_camp_upd on campaigns for update to authenticated
  using (org_id in (select id from organizations where dono_id = (select auth.uid())));
create policy p_camp_del on campaigns for delete to authenticated
  using (org_id in (select id from organizations where dono_id = (select auth.uid())));

-- 4. Campaign_members — o dono da org gerencia; membro se vê
drop policy if exists p_campmem_sel on campaign_members;
drop policy if exists p_campmem_all on campaign_members;
drop policy if exists p_campmem_ins on campaign_members;
drop policy if exists p_campmem_del on campaign_members;
create policy p_campmem_sel on campaign_members for select to authenticated
  using (user_id = (select auth.uid()) or is_campaign_member(campaign_id));
create policy p_campmem_ins on campaign_members for insert to authenticated
  with check (campaign_id in (
    select c.id from campaigns c join organizations o on o.id = c.org_id
     where o.dono_id = (select auth.uid())
  ) or user_id = (select auth.uid()));
create policy p_campmem_del on campaign_members for delete to authenticated
  using (campaign_id in (
    select c.id from campaigns c join organizations o on o.id = c.org_id
     where o.dono_id = (select auth.uid())
  ));

-- 5. Supporters — mantém regra de papel + campanha ativa
drop policy if exists p_sup_sel on supporters;
drop policy if exists p_sup_ins on supporters;
drop policy if exists p_sup_upd on supporters;
create policy p_sup_sel on supporters for select to authenticated
  using (deleted_at is null and can_read_supporters(campaign_id) and campaign_ativa(campaign_id));
create policy p_sup_ins on supporters for insert to authenticated
  with check (can_write_supporters(campaign_id) and campaign_ativa(campaign_id));
create policy p_sup_upd on supporters for update to authenticated
  using (can_write_supporters(campaign_id) and campaign_ativa(campaign_id));

-- Fim do patch.
