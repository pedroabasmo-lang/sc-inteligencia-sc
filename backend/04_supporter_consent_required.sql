-- ============================================================================
-- 04_supporter_consent_required.sql — Consentimento obrigatório em apoiadores +
-- registro automático de prova em supporter_consents. NÃO reescreve 01/02/03.
-- ============================================================================
BEGIN;

-- 1. Remover EXCLUSIVAMENTE o registro de teste sem consentimento, validando
--    que existe exatamente 1 linha com o id/nome/consentimento esperados.
do $$
declare
  alvo integer;
  invalidos integer;
begin
  select count(*) into alvo
  from public.supporters
  where id = '3ed4a930-6bab-4478-954b-8b01ec634907'
    and nome = 'Novo apoiador'
    and consentimento_em is null;
  select count(*) into invalidos
  from public.supporters
  where consentimento_em is null;
  if alvo = 1 and invalidos = 1 then
    delete from public.supporters
    where id = '3ed4a930-6bab-4478-954b-8b01ec634907';
  elsif alvo = 0 and invalidos = 0 then
    -- O registro de teste já não existe e não há outro inválido.
    null;
  else
    raise exception
      'Abortado: registro autorizado encontrado=%, total sem consentimento=%',
      alvo, invalidos;
  end if;
end
$$;

-- 2. CHECK VALID: nenhum apoiador pode existir sem consentimento_em.
alter table public.supporters
  add constraint supporters_consentimento_chk
  check (consentimento_em is not null);

-- 3. p_sup_ins recriada preservando as condições atuais e exigindo consentimento
--    completo (timestamp, base legal, prova e origem).
drop policy if exists p_sup_ins on public.supporters;
create policy p_sup_ins on public.supporters for insert to authenticated
  with check (
    can_write_supporters(campaign_id)
    and campaign_ativa(campaign_id)
    and consentimento_em is not null
    and base_legal = 'consentimento'
    and consentimento_prova is not null and length(btrim(consentimento_prova)) > 0
    and origem is not null and length(btrim(origem)) > 0
  );

-- 4. Trigger que grava a prova de consentimento em supporter_consents, na mesma
--    transação do INSERT do apoiador (falha aqui reverte o cadastro).
create or replace function public.registra_consentimento()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.supporter_consents(supporter_id, tipo, prova, data, revogado_em)
  values (new.id, 'cadastro_apoiador', new.consentimento_prova, new.consentimento_em, null);
  return null;
end;
$$;

drop trigger if exists trg_registra_consentimento on public.supporters;
create trigger trg_registra_consentimento after insert on public.supporters
  for each row execute function public.registra_consentimento();

-- Não alterados: registros antigos com consentimento, p_sup_sel, p_sup_upd,
-- campanhas, autenticação, demais RLS, migrations 01/02/03.

COMMIT;
