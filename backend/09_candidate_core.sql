-- ============================================================================
-- 09_candidate_core.sql — Núcleo estrutural público do Modelo C.
--
-- Cria APENAS: candidates, candidacies, candidacy_members, com constraints,
-- índices e FKs compostas de isolamento organizacional. Tabelas nascem
-- FECHADAS (RLS habilitada, sem policies, sem grants para anon/authenticated).
--
-- NÃO cria: policies funcionais, RPCs, auditoria, backfill, views, triggers,
-- candidate_private_profiles, candidate_party_history, campaign_strategy,
-- documentos, financeiro, jurídico, contratos. NÃO altera campos legados de
-- campaigns além de adicionar o UNIQUE(id, org_id) necessário à FK composta.
-- NÃO usa DROP, não apaga dados, não faz backfill.
--
-- Observação de convenção: o restante do projeto usa uuid_generate_v4()
-- (extensão uuid-ossp). Esta migration usa gen_random_uuid() conforme
-- especificação; a função é nativa no PostgreSQL 13+ (base do Supabase),
-- não exigindo criação de extensão.
-- ============================================================================
BEGIN;

-- ─────────────────────────────────────────────────────────────────────────
-- 0. Pré-requisito em campaigns: UNIQUE(id, org_id) para as FKs compostas.
--    Aborta se houver campanha com org_id NULL (isolamento seria burlável).
-- ─────────────────────────────────────────────────────────────────────────
do $$
declare
  n_null integer;
begin
  select count(*) into n_null from public.campaigns where org_id is null;
  if n_null > 0 then
    raise exception
      'Abortado: existem % campanha(s) com org_id NULL; a FK composta de isolamento exige org_id preenchido em todas.',
      n_null;
  end if;
end;
$$;

alter table public.campaigns
  add constraint campaigns_id_org_uk unique (id, org_id);

-- ─────────────────────────────────────────────────────────────────────────
-- 1. candidates — identidade pública mínima, isolada por organização.
-- ─────────────────────────────────────────────────────────────────────────
create table public.candidates (
  id                     uuid not null default gen_random_uuid(),
  org_id                 uuid not null,
  user_id                uuid,
  nome_cadastro          text not null,
  nome_civil             text,
  identidade_confirmada  boolean not null default false,
  nome_politico          text,
  nome_urna_preferencial text,
  biografia_publica      text,
  profissao              text,
  formacao_publica       text,
  site                   text,
  redes_publicas         jsonb,
  foto_path              text,
  criado_por             uuid,
  criado_em              timestamptz not null default now(),
  atualizado_por         uuid,
  atualizado_em          timestamptz not null default now(),
  deleted_at             timestamptz,
  constraint candidates_pkey primary key (id),
  constraint candidates_id_org_uk unique (id, org_id),
  constraint candidates_org_fk       foreign key (org_id)     references public.organizations(id) on delete restrict,
  constraint candidates_user_fk      foreign key (user_id)    references public.profiles(id)      on delete set null,
  constraint candidates_criado_fk    foreign key (criado_por) references public.profiles(id)      on delete set null,
  constraint candidates_atualizado_fk foreign key (atualizado_por) references public.profiles(id) on delete set null,
  constraint candidates_nome_cadastro_chk check (btrim(nome_cadastro) <> ''),
  constraint candidates_redes_obj_chk     check (redes_publicas is null or jsonb_typeof(redes_publicas) = 'object')
);

-- índices candidates (não redundantes com PK/UNIQUE já existentes)
create index candidates_org_ativos_idx on public.candidates(org_id) where deleted_at is null;
create index candidates_nome_cadastro_idx on public.candidates(nome_cadastro);
-- uma conta de usuário no máximo um candidato ativo por organização
create unique index candidates_org_user_uk
  on public.candidates(org_id, user_id)
  where user_id is not null and deleted_at is null;

-- ─────────────────────────────────────────────────────────────────────────
-- 2. candidacies — uma disputa eleitoral (nunca uma pessoa da chapa).
-- ─────────────────────────────────────────────────────────────────────────
create table public.candidacies (
  id                    uuid not null default gen_random_uuid(),
  org_id                uuid not null,
  campaign_id           uuid,
  nome_urna             text,
  ano                   smallint not null,
  turno                 smallint,
  cargo                 text not null,
  uf                    char(2),
  municipio_ibge        text,
  abrangencia           text not null,
  numero                text,
  sigla_partido_disputa text,
  federacao_coligacao   text,
  sequencial_tse        text,
  fase                  text not null default 'pre_candidatura',
  status_registro       text not null default 'nao_iniciado',
  status_recurso        text not null default 'sem_recurso',
  resultado_eleitoral   text not null default 'nao_apurado',
  situacao_mandato      text not null default 'nao_aplicavel',
  votacao_obtida        bigint,
  criado_por            uuid,
  criado_em             timestamptz not null default now(),
  atualizado_por        uuid,
  atualizado_em         timestamptz not null default now(),
  constraint candidacies_pkey primary key (id),
  constraint candidacies_id_org_uk unique (id, org_id),
  constraint candidacies_campaign_uk unique (campaign_id),
  constraint candidacies_org_fk        foreign key (org_id)     references public.organizations(id) on delete restrict,
  constraint candidacies_criado_fk     foreign key (criado_por) references public.profiles(id)      on delete set null,
  constraint candidacies_atualizado_fk foreign key (atualizado_por) references public.profiles(id)  on delete set null,
  constraint candidacies_campaign_org_fk
    foreign key (campaign_id, org_id) references public.campaigns(id, org_id) on delete restrict,
  constraint candidacies_ano_chk         check (ano between 1990 and 2100),
  constraint candidacies_turno_chk       check (turno is null or turno in (1,2)),
  constraint candidacies_uf_chk          check (uf is null or uf in
    ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB',
     'PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO')),
  constraint candidacies_municipio_ibge_chk check (municipio_ibge is null or municipio_ibge ~ '^[0-9]{7}$'),
  constraint candidacies_numero_chk      check (numero is null or numero ~ '^[0-9]+$'),
  constraint candidacies_sequencial_chk  check (sequencial_tse is null or sequencial_tse ~ '^[0-9]+$'),
  constraint candidacies_votacao_chk     check (votacao_obtida is null or votacao_obtida >= 0),
  constraint candidacies_cargo_chk       check (cargo in
    ('presidente','governador','senador','deputado_federal','deputado_estadual',
     'deputado_distrital','prefeito','vereador')),
  constraint candidacies_abrangencia_chk check (abrangencia in
    ('nacional','estadual','distrital','municipal')),
  constraint candidacies_fase_chk        check (fase in
    ('pre_candidatura','candidatura','mandato','encerrada')),
  constraint candidacies_status_registro_chk check (status_registro in
    ('nao_iniciado','pendente','deferido','indeferido','cancelado')),
  constraint candidacies_status_recurso_chk  check (status_recurso in
    ('sem_recurso','em_recurso','encerrado')),
  constraint candidacies_resultado_chk   check (resultado_eleitoral in
    ('nao_apurado','segundo_turno','eleito','nao_eleito','suplente')),
  constraint candidacies_situacao_mandato_chk check (situacao_mandato in
    ('nao_aplicavel','em_exercicio','renuncia','cassacao','afastamento','falecimento','mandato_encerrado'))
);

-- índices candidacies (campaign_id já coberto pelo UNIQUE candidacies_campaign_uk)
create index candidacies_org_idx on public.candidacies(org_id);
create index candidacies_ano_uf_cargo_idx on public.candidacies(ano, uf, cargo);
create index candidacies_sequencial_idx on public.candidacies(sequencial_tse);

-- ─────────────────────────────────────────────────────────────────────────
-- 3. candidacy_members — composição da chapa (mesma org por FKs compostas).
-- ─────────────────────────────────────────────────────────────────────────
create table public.candidacy_members (
  id           uuid not null default gen_random_uuid(),
  org_id       uuid not null,
  candidacy_id uuid not null,
  candidate_id uuid not null,
  papel        text not null,
  ordem        smallint,
  is_principal boolean not null default false,
  criado_por   uuid,
  criado_em    timestamptz not null default now(),
  constraint candidacy_members_pkey primary key (id),
  constraint candidacy_members_cand_pessoa_uk unique (candidacy_id, candidate_id),
  constraint candidacy_members_criado_fk foreign key (criado_por) references public.profiles(id) on delete set null,
  constraint candidacy_members_candidacy_org_fk
    foreign key (candidacy_id, org_id) references public.candidacies(id, org_id) on delete cascade,
  constraint candidacy_members_candidate_org_fk
    foreign key (candidate_id, org_id) references public.candidates(id, org_id) on delete restrict,
  constraint candidacy_members_ordem_chk check (ordem is null or ordem >= 1),
  constraint candidacy_members_papel_chk check (papel in
    ('titular','vice','primeiro_suplente','segundo_suplente','coletivo'))
);

-- índices de apoio
create index candidacy_members_candidacy_idx on public.candidacy_members(candidacy_id);
create index candidacy_members_candidate_idx on public.candidacy_members(candidate_id);
-- ordem única dentro da candidatura, quando informada
create unique index candidacy_members_ordem_uk
  on public.candidacy_members(candidacy_id, ordem) where ordem is not null;
-- papéis exclusivos: no máximo um de cada por candidatura (coletivo pode repetir)
create unique index candidacy_members_titular_uk
  on public.candidacy_members(candidacy_id) where papel = 'titular';
create unique index candidacy_members_vice_uk
  on public.candidacy_members(candidacy_id) where papel = 'vice';
create unique index candidacy_members_prim_supl_uk
  on public.candidacy_members(candidacy_id) where papel = 'primeiro_suplente';
create unique index candidacy_members_seg_supl_uk
  on public.candidacy_members(candidacy_id) where papel = 'segundo_suplente';
-- no máximo um principal por candidatura
create unique index candidacy_members_principal_uk
  on public.candidacy_members(candidacy_id) where is_principal = true;

-- ─────────────────────────────────────────────────────────────────────────
-- 4. Segurança preventiva: RLS habilitada, SEM policies, SEM grants.
--    As tabelas ficam inacessíveis a anon e authenticated até a migration 10.
--    (Não se usa FORCE ROW LEVEL SECURITY: como não há grants, anon/authenticated
--     já não conseguem acessar; o dono da tabela ignora RLS por padrão, o que é o
--     comportamento desejado durante a fase estrutural.)
-- ─────────────────────────────────────────────────────────────────────────
alter table public.candidates        enable row level security;
alter table public.candidacies       enable row level security;
alter table public.candidacy_members enable row level security;

revoke all on public.candidates        from public;
revoke all on public.candidates        from anon, authenticated;
revoke all on public.candidacies       from public;
revoke all on public.candidacies       from anon, authenticated;
revoke all on public.candidacy_members from public;
revoke all on public.candidacy_members from anon, authenticated;

COMMIT;
