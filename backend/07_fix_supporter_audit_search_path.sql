-- ============================================================================
-- 07_fix_supporter_audit_search_path.sql — Recria public.audita_supporters()
-- com search_path fixo e objetos qualificados, para funcionar quando disparada
-- dentro de RPCs com search_path=''. NÃO altera trigger, formato nem RLS.
-- ============================================================================
BEGIN;

create or replace function public.audita_supporters()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (
    coalesce(new.campaign_id, old.campaign_id), auth.uid(), tg_op, 'supporters',
    coalesce(new.id, old.id)::text,
    case when tg_op <> 'INSERT' then to_jsonb(old) end,
    case when tg_op <> 'DELETE' then to_jsonb(new) end
  );
  return coalesce(new, old);
end;
$$;

-- trg_audita_supporters (AFTER INSERT OR UPDATE OR DELETE) permanece; aponta
-- para esta mesma função pelo nome, sem necessidade de recriá-lo.

COMMIT;
