-- ============================================================================
-- 03_campaign_lifecycle.sql — Ciclo de vida da campanha (arquivar / restaurar /
-- excluir só quando vazia). NÃO reescreve 01 nem 02. Rodar após ambos.
-- ============================================================================
BEGIN;

-- 1. Colunas de arquivamento
alter table public.campaigns add column if not exists archived_at timestamptz;
alter table public.campaigns add column if not exists archived_by uuid null
  references public.profiles(id) on delete restrict;

-- 2. FK supporters.campaign_id: CASCADE -> RESTRICT (regra no banco: não excluir
--    campanha que tenha qualquer apoiador; não apaga supporters em cascata).
alter table public.supporters drop constraint if exists supporters_campaign_id_fkey;
alter table public.supporters add constraint supporters_campaign_id_fkey
  foreign key (campaign_id) references public.campaigns(id) on delete restrict;

-- 3. Índice de apoio à FK / consultas por campanha
create index if not exists idx_supporters_campaign_id
  on public.supporters(campaign_id);

-- 4. archived_by é sempre definido pelo banco (nunca pelo frontend).
create or replace function public.set_archived_by()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if new.archived_at is not null then
      new.archived_by := auth.uid();
    else
      new.archived_by := null;
    end if;
  elsif tg_op = 'UPDATE' then
    if new.archived_at is distinct from old.archived_at then
      if new.archived_at is not null then
        new.archived_by := auth.uid();
      else
        new.archived_by := null;
      end if;
    else
      new.archived_by := old.archived_by;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_set_archived_by on public.campaigns;
create trigger trg_set_archived_by before insert or update on public.campaigns
  for each row execute function public.set_archived_by();

-- 5. Auditoria de arquivar / restaurar / excluir (colunas reais de audit_log).
create or replace function public.audita_campaigns()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
    values (old.id, auth.uid(), 'DELETE', 'campaigns', old.id::text, to_jsonb(old), null);
    return null;
  elsif tg_op = 'UPDATE' then
    insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
    values (
      new.id, auth.uid(),
      case
        when old.archived_at is null and new.archived_at is not null then 'ARCHIVE'
        when old.archived_at is not null and new.archived_at is null then 'RESTORE'
        else 'UPDATE'
      end,
      'campaigns', new.id::text, to_jsonb(old), to_jsonb(new));
    return null;
  end if;
  return null;
end;
$$;

drop trigger if exists trg_audita_campaigns on public.campaigns;
create trigger trg_audita_campaigns after update or delete on public.campaigns
  for each row execute function public.audita_campaigns();

-- Mantidos sem alteração: campaign_members ON DELETE CASCADE (01),
-- p_camp_del e p_camp_upd (02), RLS ativa, supporter_consents.

COMMIT;
