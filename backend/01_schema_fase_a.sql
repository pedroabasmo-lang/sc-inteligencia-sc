-- ============================================================================
-- Fase A — Backend multi-tenant (Supabase / PostgreSQL)
-- Organização → Campanha → Membros → Apoiadores, com RLS e LGPD.
-- Rodar no SQL Editor do Supabase (uma vez). Idempotente onde possível.
-- ============================================================================

-- Extensões
create extension if not exists "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Perfis (espelha auth.users do Supabase)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  nome text,
  email text,
  criado_em timestamptz default now()
);

-- cria profile automaticamente quando um usuário se cadastra
create or replace function handle_new_user() returns trigger
language plpgsql security definer as $$
begin
  insert into profiles(id, nome, email)
  values (new.id, coalesce(new.raw_user_meta_data->>'nome', new.email), new.email)
  on conflict (id) do nothing;
  return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function handle_new_user();

-- ─────────────────────────────────────────────────────────────────────────
-- 2. Organização (a consultoria) e Campanhas (candidatos)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists organizations (
  id uuid primary key default uuid_generate_v4(),
  nome text not null,
  dono_id uuid not null references profiles(id),
  criada_em timestamptz default now()
);

create table if not exists organization_members (
  org_id uuid references organizations(id) on delete cascade,
  user_id uuid references profiles(id) on delete cascade,
  papel_org text not null default 'membro' check (papel_org in ('dono','admin','membro')),
  primary key (org_id, user_id)
);

create table if not exists campaigns (
  id uuid primary key default uuid_generate_v4(),
  org_id uuid not null references organizations(id) on delete cascade,
  candidato_nome text not null,
  nome_urna text,
  cargo text,           -- dep_federal, dep_estadual, senador, prefeito, governador...
  uf text,
  numero text,
  partido text,
  -- controle COMERCIAL (definido pelo dono da consultoria; cobrança é feita por fora)
  tipo_comercial text not null default 'doada' check (tipo_comercial in ('doada','vendida')),
  valor_texto text,     -- livre: 'R$ 3.000 fechado', 'R$ 500/mês', 'parceria', etc.
  modelo_cobranca text default 'unico' check (modelo_cobranca in ('unico','mensal')),
  situacao text not null default 'ativa' check (situacao in ('ativa','suspensa','expirada')),
  expira_em date,       -- opcional: acesso vale até esta data
  criada_por uuid references profiles(id),
  criada_em timestamptz default now()
);

create table if not exists campaign_members (
  campaign_id uuid references campaigns(id) on delete cascade,
  user_id uuid references profiles(id) on delete cascade,
  papel text not null check (papel in (
    'admin','candidato','coord_geral','coord_regional','coord_municipal',
    'mobilizacao','financeiro','contabilidade','juridico','comunicacao',
    'fiscalizacao','consulta')),
  escopo text,          -- p/ coord_regional/municipal: região ou cidade que enxerga
  criado_em timestamptz default now(),
  primary key (campaign_id, user_id)
);

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Apoiadores (dado pessoal/sensível → LGPD)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists supporters (
  id uuid primary key default uuid_generate_v4(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  nome text not null,
  telefone text,
  whatsapp text,
  email text,
  cidade text,
  bairro text,
  funcao text,
  nivel int check (nivel between 1 and 5),
  nasc date,
  obs text,
  -- LGPD
  origem text,                       -- de onde veio o dado (evento, indicação, importação…)
  base_legal text default 'consentimento',
  consentimento_em timestamptz,
  consentimento_prova text,          -- link/descrição da prova (formulário, print…)
  canais_ok text[] default '{}',     -- canais autorizados: whatsapp, email, sms, ligacao
  -- trilha
  criado_por uuid references profiles(id),
  criado_em timestamptz default now(),
  atualizado_por uuid references profiles(id),
  atualizado_em timestamptz default now(),
  deleted_at timestamptz             -- exclusão lógica (descadastramento)
);
create index if not exists idx_supporters_campaign on supporters(campaign_id) where deleted_at is null;

create table if not exists supporter_consents (
  id uuid primary key default uuid_generate_v4(),
  supporter_id uuid references supporters(id) on delete cascade,
  tipo text,                         -- 'cadastro', 'comunicacao', 'compartilhamento'
  prova text,
  data timestamptz default now(),
  revogado_em timestamptz
);

-- ─────────────────────────────────────────────────────────────────────────
-- 4. Auditoria (quem fez o quê, quando)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists audit_log (
  id bigserial primary key,
  campaign_id uuid,
  user_id uuid,
  acao text,                         -- INSERT, UPDATE, DELETE, LOGIN…
  entidade text,                     -- supporters, campaigns…
  entidade_id text,
  antes jsonb,
  depois jsonb,
  criado_em timestamptz default now()
);

-- ─────────────────────────────────────────────────────────────────────────
-- 5. Funções de apoio à segurança (RLS)
-- ─────────────────────────────────────────────────────────────────────────
create or replace function is_org_owner(p_org uuid) returns boolean
language sql stable security definer as $$
  select exists (
    select 1 from organizations o where o.id = p_org and o.dono_id = auth.uid()
    union
    select 1 from organization_members m
     where m.org_id = p_org and m.user_id = auth.uid() and m.papel_org in ('dono','admin')
  );
$$;

create or replace function is_campaign_member(p_campaign uuid) returns boolean
language sql stable security definer as $$
  select exists (
    select 1 from campaign_members cm
     where cm.campaign_id = p_campaign and cm.user_id = auth.uid()
  ) or exists (
    select 1 from campaigns c
     where c.id = p_campaign and is_org_owner(c.org_id)
  );
$$;

create or replace function campaign_role(p_campaign uuid) returns text
language sql stable security definer as $$
  select coalesce(
    (select papel from campaign_members
      where campaign_id = p_campaign and user_id = auth.uid() limit 1),
    (select 'admin' from campaigns c
      where c.id = p_campaign and is_org_owner(c.org_id) limit 1)
  );
$$;

-- papéis que podem ver/editar apoiadores
create or replace function can_read_supporters(p_campaign uuid) returns boolean
language sql stable as $$
  select campaign_role(p_campaign) in
    ('admin','candidato','coord_geral','coord_regional','coord_municipal','mobilizacao','consulta');
$$;
create or replace function can_write_supporters(p_campaign uuid) returns boolean
language sql stable as $$
  select campaign_role(p_campaign) in ('admin','coord_geral','coord_municipal','mobilizacao');
$$;

-- campanha está com acesso liberado? (situação + vigência)
create or replace function campaign_ativa(p_campaign uuid) returns boolean
language sql stable security definer as $$
  select exists (
    select 1 from campaigns c
     where c.id = p_campaign and c.situacao = 'ativa'
       and (c.expira_em is null or c.expira_em >= current_date)
  );
$$;

-- ─────────────────────────────────────────────────────────────────────────
-- 6. RLS (liga o isolamento entre campanhas no nível do banco)
-- ─────────────────────────────────────────────────────────────────────────
alter table profiles              enable row level security;
alter table organizations         enable row level security;
alter table organization_members  enable row level security;
alter table campaigns             enable row level security;
alter table campaign_members      enable row level security;
alter table supporters            enable row level security;
alter table supporter_consents    enable row level security;
alter table audit_log             enable row level security;

-- profiles: cada um vê/edita o próprio; membros da mesma campanha se enxergam por nome
drop policy if exists p_profiles_self on profiles;
create policy p_profiles_self on profiles for all
  using (id = auth.uid()) with check (id = auth.uid());

-- organizations: dono e membros veem; só dono cria/edita
drop policy if exists p_org_sel on organizations;
create policy p_org_sel on organizations for select using (is_org_owner(id) or dono_id = auth.uid());
drop policy if exists p_org_ins on organizations;
create policy p_org_ins on organizations for insert with check (dono_id = auth.uid());
drop policy if exists p_org_upd on organizations;
create policy p_org_upd on organizations for update using (dono_id = auth.uid());

drop policy if exists p_orgmem_sel on organization_members;
create policy p_orgmem_sel on organization_members for select using (is_org_owner(org_id) or user_id = auth.uid());
drop policy if exists p_orgmem_all on organization_members;
create policy p_orgmem_all on organization_members for all using (is_org_owner(org_id)) with check (is_org_owner(org_id));

-- campaigns: membros e dono da org veem; só dono/admin da org cria/edita (inclui status comercial)
drop policy if exists p_camp_sel on campaigns;
create policy p_camp_sel on campaigns for select using (is_campaign_member(id));
drop policy if exists p_camp_ins on campaigns;
create policy p_camp_ins on campaigns for insert with check (is_org_owner(org_id));
drop policy if exists p_camp_upd on campaigns;
create policy p_camp_upd on campaigns for update using (is_org_owner(org_id));
drop policy if exists p_camp_del on campaigns;
create policy p_camp_del on campaigns for delete using (is_org_owner(org_id));

drop policy if exists p_campmem_sel on campaign_members;
create policy p_campmem_sel on campaign_members for select using (is_campaign_member(campaign_id));
drop policy if exists p_campmem_all on campaign_members;
create policy p_campmem_all on campaign_members for all
  using (campaign_role(campaign_id) = 'admin') with check (campaign_role(campaign_id) = 'admin');

-- supporters: só membros com papel adequado E campanha ativa
drop policy if exists p_sup_sel on supporters;
create policy p_sup_sel on supporters for select
  using (deleted_at is null and can_read_supporters(campaign_id) and campaign_ativa(campaign_id));
drop policy if exists p_sup_ins on supporters;
create policy p_sup_ins on supporters for insert
  with check (can_write_supporters(campaign_id) and campaign_ativa(campaign_id));
drop policy if exists p_sup_upd on supporters;
create policy p_sup_upd on supporters for update
  using (can_write_supporters(campaign_id) and campaign_ativa(campaign_id));

drop policy if exists p_supcons_all on supporter_consents;
create policy p_supcons_all on supporter_consents for all
  using (exists (select 1 from supporters s where s.id = supporter_id and can_read_supporters(s.campaign_id)))
  with check (exists (select 1 from supporters s where s.id = supporter_id and can_write_supporters(s.campaign_id)));

-- audit_log: admin/candidato leem; qualquer membro insere (via app)
drop policy if exists p_audit_sel on audit_log;
create policy p_audit_sel on audit_log for select
  using (campaign_role(campaign_id) in ('admin','candidato'));
drop policy if exists p_audit_ins on audit_log;
create policy p_audit_ins on audit_log for insert with check (is_campaign_member(campaign_id));

-- ─────────────────────────────────────────────────────────────────────────
-- 7. Auditoria automática de apoiadores (INSERT/UPDATE/DELETE)
-- ─────────────────────────────────────────────────────────────────────────
create or replace function audita_supporters() returns trigger
language plpgsql security definer as $$
begin
  insert into audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (
    coalesce(new.campaign_id, old.campaign_id), auth.uid(), tg_op, 'supporters',
    coalesce(new.id, old.id)::text,
    case when tg_op <> 'INSERT' then to_jsonb(old) end,
    case when tg_op <> 'DELETE' then to_jsonb(new) end
  );
  return coalesce(new, old);
end; $$;

drop trigger if exists trg_audita_supporters on supporters;
create trigger trg_audita_supporters after insert or update or delete on supporters
  for each row execute function audita_supporters();

-- Fim da Fase A.
