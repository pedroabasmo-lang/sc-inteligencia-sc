-- ============================================================================
-- 11_campaign_candidate_backfill.sql — RPC de conversão de campanha legada para
-- o Modelo C (candidates, candidacies, candidacy_members).
--
-- Cria EXCLUSIVAMENTE a função public.backfill_campaign_candidate_model.
-- Não cria tabelas, índices, policies, triggers, tabela de controle; não altera
-- campaigns, as migrations 09/10, nem o frontend; não vincula candidates.user_id;
-- não executa backfill automático (a chamada é manual, posterior).
--
-- Depende das migrations 09 (estrutura + FKs compostas + UNIQUE campaign_id) e
-- 10 (RLS, triggers de proteção/autoria/auditoria, privilégios por coluna).
-- Sendo SECURITY DEFINER, a função contorna RLS/grants legitimamente para inserir
-- candidacy já com campaign_id; a autorização é feita no corpo (proprietário real).
-- Não desativa RLS nem triggers; não usa variável de sessão; não usa bypass.
-- ============================================================================
BEGIN;

create or replace function public.backfill_campaign_candidate_model(
  p_campaign uuid,
  p_ano      smallint,
  p_cargo    text default null
)
returns table (
  candidate_id uuid,
  candidacy_id uuid,
  member_id    uuid,
  ja_existia   boolean
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid          uuid := auth.uid();
  v_org          uuid;
  v_dono         uuid;
  v_nome         text;
  v_nome_urna    text;
  v_uf_raw       text;
  v_uf           text;
  v_num_raw      text;
  v_numero       text;
  v_partido      text;
  v_cargo_raw    text;
  v_cargo_norm   text;
  v_cargo_canon  text;
  v_abrangencia  text;
  v_cand         uuid;
  v_candidacy    uuid;
  v_member       uuid;
begin
  -- 1. Autenticação.
  if v_uid is null then
    raise exception 'Não autenticado.';
  end if;

  -- 2. Localizar a campanha e travá-la (serializa chamadas concorrentes antes
  --    da verificação de idempotência; a 2ª chamada espera e depois vê o já feito).
  select c.org_id, c.candidato_nome, c.nome_urna, c.cargo, c.uf, c.numero, c.partido
    into v_org, v_nome, v_nome_urna, v_cargo_raw, v_uf_raw, v_num_raw, v_partido
    from public.campaigns c
   where c.id = p_campaign
   for update;
  if not found then
    raise exception 'Campanha não encontrada.';
  end if;
  if v_org is null then
    raise exception 'Campanha sem organização associada.';
  end if;

  -- 3. Autorização: somente o PROPRIETÁRIO REAL da organização (dono_id).
  select o.dono_id into v_dono
    from public.organizations o
   where o.id = v_org;
  if v_dono is distinct from v_uid then
    raise exception 'Apenas o proprietário da organização pode converter esta campanha.';
  end if;

  -- 4. Idempotência: campanha já convertida?
  select cy.id into v_candidacy
    from public.candidacies cy
   where cy.campaign_id = p_campaign;
  if v_candidacy is not null then
    select cm.id, cm.candidate_id into v_member, v_cand
      from public.candidacy_members cm
     where cm.candidacy_id = v_candidacy and cm.is_principal = true;
    if v_member is null then
      raise exception 'Conversão anterior incompleta: candidacy % existe sem membro principal.', v_candidacy;
    end if;
    candidate_id := v_cand;
    candidacy_id := v_candidacy;
    member_id    := v_member;
    ja_existia   := true;
    return next;
    return;
  end if;

  -- 5. Validação do ano (mensagem clara antes do INSERT).
  if p_ano is null or p_ano < 1990 or p_ano > 2100 then
    raise exception 'Ano inválido: % (esperado entre 1990 e 2100).', p_ano;
  end if;

  -- 6. Normalização e mapeamento do cargo.
  v_cargo_norm := coalesce(p_cargo, v_cargo_raw);
  v_cargo_norm := lower(btrim(v_cargo_norm));
  v_cargo_norm := regexp_replace(v_cargo_norm, '[ ./-]+', '_', 'g'); -- espaços, ponto, barra, hífen → _
  v_cargo_norm := regexp_replace(v_cargo_norm, '_+', '_', 'g');       -- underscores repetidos → 1
  v_cargo_norm := btrim(v_cargo_norm, '_');                            -- remove _ nas pontas
  v_cargo_canon := case v_cargo_norm
    when 'presidente'          then 'presidente'
    when 'governador'          then 'governador'
    when 'senador'             then 'senador'
    when 'dep_federal'         then 'deputado_federal'
    when 'deputado_federal'    then 'deputado_federal'
    when 'dep_estadual'        then 'deputado_estadual'
    when 'deputado_estadual'   then 'deputado_estadual'
    when 'dep_distrital'       then 'deputado_distrital'
    when 'deputado_distrital'  then 'deputado_distrital'
    when 'prefeito'            then 'prefeito'
    when 'vereador'            then 'vereador'
    else null
  end;
  if v_cargo_canon is null then
    raise exception 'Cargo não reconhecido: "%". Informe p_cargo com um cargo canônico (presidente, governador, senador, deputado_federal, deputado_estadual, deputado_distrital, prefeito, vereador).',
      coalesce(p_cargo, v_cargo_raw);
  end if;

  -- 7. Abrangência derivada exclusivamente do cargo canônico.
  v_abrangencia := case v_cargo_canon
    when 'presidente'         then 'nacional'
    when 'governador'         then 'estadual'
    when 'senador'            then 'estadual'
    when 'deputado_federal'   then 'estadual'
    when 'deputado_estadual'  then 'estadual'
    when 'deputado_distrital' then 'distrital'
    when 'prefeito'           then 'municipal'
    when 'vereador'           then 'municipal'
  end;

  -- 8. UF: nula/vazia → NULL; senão upper(btrim) e validação contra as 27 UFs.
  if v_uf_raw is null or btrim(v_uf_raw) = '' then
    v_uf := null;
  else
    v_uf := upper(btrim(v_uf_raw));
    -- Validar formato ANTES de qualquer conversão de tipo, para não truncar
    -- silenciosamente valores com mais de duas letras (ex.: "SCC" → "SC").
    if v_uf !~ '^[A-Z]{2}$' then
      raise exception 'UF inválida: "%".', v_uf_raw;
    end if;
    if v_uf not in
      ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB',
       'PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO') then
      raise exception 'UF inválida: "%".', v_uf_raw;
    end if;
  end if;
  -- Qualquer cargo diferente de presidente exige UF válida e não nula.
  if v_cargo_canon <> 'presidente' and v_uf is null then
    raise exception 'UF é obrigatória para o cargo %.', v_cargo_canon;
  end if;

  -- 9. Número: nulo/vazio → NULL; só dígitos → mantém; com não-dígitos → erro.
  if v_num_raw is null or btrim(v_num_raw) = '' then
    v_numero := null;
  elsif btrim(v_num_raw) ~ '^[0-9]+$' then
    v_numero := btrim(v_num_raw);
  else
    raise exception 'Número inválido: "%" (apenas dígitos são aceitos).', v_num_raw;
  end if;

  -- 10. Candidato: nome_cadastro obrigatório e não vazio; sem deduplicar por nome.
  if v_nome is null or btrim(v_nome) = '' then
    raise exception 'Campanha sem candidato_nome válido.';
  end if;

  insert into public.candidates (org_id, user_id, nome_cadastro, identidade_confirmada)
  values (v_org, null, btrim(v_nome), false)
  returning id into v_cand;

  -- 11. Candidatura (campaign_id preenchido; permitido pois a função é definer).
  insert into public.candidacies (
    org_id, campaign_id, nome_urna, ano, cargo, uf, numero, sigla_partido_disputa, abrangencia
  ) values (
    v_org,
    p_campaign,
    coalesce(nullif(btrim(v_nome_urna), ''), btrim(v_nome)),
    p_ano,
    v_cargo_canon,
    v_uf,
    v_numero,
    upper(nullif(btrim(v_partido), '')),
    v_abrangencia
  )
  returning id into v_candidacy;

  -- 12. Composição: titular e principal.
  insert into public.candidacy_members (org_id, candidacy_id, candidate_id, papel, ordem, is_principal)
  values (v_org, v_candidacy, v_cand, 'titular', 1, true)
  returning id into v_member;

  candidate_id := v_cand;
  candidacy_id := v_candidacy;
  member_id    := v_member;
  ja_existia   := false;
  return next;
end;
$$;

revoke all on function public.backfill_campaign_candidate_model(uuid, smallint, text) from public, anon;
grant execute on function public.backfill_campaign_candidate_model(uuid, smallint, text) to authenticated;

COMMIT;

-- ============================================================================
-- TESTES A EXECUTAR APÓS APLICAR A 11 (não executados aqui):
--  1.  proprietário converte campanha válida → cria candidate, candidacy, member.
--  2.  cargo "Dep. Federal" (ou dep_federal) resulta em 'deputado_federal'.
--  3.  abrangência resultante do cargo deputado_federal é 'estadual'.
--  4.  UF 'SC' é preservada.
--  5.  número nulo permanece nulo.
--  6.  partido 'PSD' é preservado em sigla_partido_disputa (upper).
--  7.  candidates.user_id permanece NULL.
--  8.  segunda chamada para a mesma campanha retorna ja_existia = true.
--  9.  segunda chamada não cria candidate/candidacy/member duplicados.
--  10. usuário não proprietário (admin de org ou papel de campanha) é negado.
--  11. membro de campanha é negado.
--  12. usuário não autenticado é negado.
--  13. campanha inexistente é negada.
--  14. ano inválido (< 1990 ou > 2100 ou nulo) é negado.
--  15. cargo desconhecido é negado com o valor legado no erro.
--  16. UF inválida é negada; UF ausente para cargo != presidente é negada.
--  17. número não numérico é negado (sem remoção silenciosa de caracteres).
--  18. candidacy vinculada sem membro principal → erro de conversão incompleta.
--  19. duas chamadas concorrentes (FOR UPDATE) não criam candidatos duplicados.
--  20. auditoria (triggers da 10) registra os três INSERTs com user_id do dono.
--  21. UF com mais de duas letras, como "SCC", é rejeitada sem truncamento.
--  22. UF com uma letra é rejeitada.
--  23. UF minúscula válida, como "sc", é normalizada para "SC".
--  24. espaços externos em " SC " são removidos (btrim).
--  25. valor de duas letras inexistente, como "XX", é rejeitado.
-- ============================================================================
