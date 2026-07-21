-- ============================================================================
-- 05_supporter_consent_immutable.sql — Reconcilia o consentimento de 'testa3'
-- com a prova real e impede alteração dos campos de consentimento por edição
-- comum. NÃO reescreve 01/02/03/04.
-- ============================================================================
BEGIN;

-- 1. Reconciliar 'testa3': consentimento_em = data da prova já gravada.
--    (executado ANTES de criar o trigger de imutabilidade)
do $$
declare
  sup_id uuid;
  prova_data timestamptz;
  n_sup integer;
  n_prova integer;
begin
  select count(*) into n_sup
  from public.supporters
  where nome = 'testa3' and email = 'teste3@teste.com';
  if n_sup <> 1 then
    raise exception 'Abortado: esperado exatamente 1 supporter testa3, encontrado %', n_sup;
  end if;

  select id into sup_id
  from public.supporters
  where nome = 'testa3' and email = 'teste3@teste.com';

  select count(*) into n_prova
  from public.supporter_consents
  where supporter_id = sup_id and tipo = 'cadastro_apoiador' and revogado_em is null;
  if n_prova <> 1 then
    raise exception 'Abortado: esperado exatamente 1 prova ativa de cadastro_apoiador, encontrado %', n_prova;
  end if;

  select data into prova_data
  from public.supporter_consents
  where supporter_id = sup_id and tipo = 'cadastro_apoiador' and revogado_em is null;

  update public.supporters
  set consentimento_em = prova_data
  where id = sup_id;
end
$$;

-- 2. Trigger BEFORE UPDATE: campos de consentimento não podem mudar por edição
--    comum. (Revogação será ação própria, fora deste escopo.)
create or replace function public.protege_consentimento()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.consentimento_em    is distinct from old.consentimento_em
  or new.consentimento_prova is distinct from old.consentimento_prova
  or new.base_legal          is distinct from old.base_legal
  or new.origem              is distinct from old.origem then
    raise exception 'Os dados do consentimento original não podem ser alterados por edição comum';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_protege_consentimento on public.supporters;
create trigger trg_protege_consentimento before update on public.supporters
  for each row execute function public.protege_consentimento();

-- Não alterados: supporter_consents (nenhuma prova nova aqui), políticas RLS,
-- campanhas, autenticação, migrations 01/02/03/04.

COMMIT;
