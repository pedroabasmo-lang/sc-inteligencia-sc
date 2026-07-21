-- ============================================================================
-- 06_supporter_unregister.sql — Descadastramento (soft delete) de apoiador via
-- função SECURITY DEFINER com autorização explícita por campanha. Não altera
-- p_sup_sel, p_sup_upd, demais RLS, consentimento ou autenticação.
-- ============================================================================
BEGIN;

create or replace function public.descadastrar_supporter(p_supporter_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_rows integer;
begin
  if v_uid is null then
    raise exception 'Não autenticado.';
  end if;

  -- Descadastrar independe da situação da campanha (ativa/arquivada/suspensa/
  -- expirada); exige apenas permissão de escrita do usuário sobre a campanha.
  update public.supporters s
  set deleted_at = now(),
      atualizado_por = v_uid,
      atualizado_em = now()
  where s.id = p_supporter_id
    and s.deleted_at is null
    and public.can_write_supporters(s.campaign_id);

  get diagnostics v_rows = row_count;
  if v_rows <> 1 then
    raise exception 'Apoiador não encontrado, já descadastrado ou sem permissão.';
  end if;
end;
$$;

-- Privilégios: só usuários autenticados podem executar.
revoke execute on function public.descadastrar_supporter(uuid) from public;
revoke execute on function public.descadastrar_supporter(uuid) from anon;
grant  execute on function public.descadastrar_supporter(uuid) to authenticated;

COMMIT;
