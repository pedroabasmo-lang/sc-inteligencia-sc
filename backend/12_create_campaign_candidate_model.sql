-- ============================================================================
-- 12_create_campaign_candidate_model.sql — Criação transacional de novas
-- campanhas já no Modelo C (campaign + candidate + candidacy + candidacy_member
-- + campaign_member do proprietário), preservando os campos legados de campaigns.
--
-- Cria EXCLUSIVAMENTE public.create_campaign_candidate_model.
-- Não cria tabelas, índices, policies, triggers, tabela de controle; não altera
-- campaigns nem as migrations 01–11; não altera o frontend; não faz backfill;
-- não vincula candidates.user_id; não altera a campanha já existente.
--
-- IDEMPOTÊNCIA POR CONTEÚDO: chave = p_campaign_id (UUID do cliente), protegida
-- por pg_advisory_xact_lock sobre hash estável do UUID. Se a campanha já existe,
-- a RPC exige que TODA a estrutura (campaigns, candidacies, candidacy_members,
-- candidate principal, campaign_member do dono) esteja completa, íntegra na mesma
-- organização E com dados equivalentes aos recalculados a partir do payload atual;
-- só então retorna ja_existia=true. Qualquer divergência ou criação parcial gera
-- erro explícito — nunca atualização silenciosa, nunca reparo, nunca duplicação.
--
-- AUTORIZAÇÃO: SECURITY DEFINER; escrita só ao proprietário real da organização
-- (organizations.dono_id = auth.uid()). Não confia em papel de campanha, admin
-- de organização, profile ou parâmetro do cliente.
--
-- AUDITORIA: candidates/candidacies/candidacy_members são auditados pelos triggers
-- da migration 10 (acao=tg_op='INSERT'). campaigns só tem trigger para UPDATE/
-- DELETE (migration 03), então o INSERT de campaign é auditado MANUALMENTE aqui
-- (acao='INSERT', depois=to_jsonb da linha inserida). campaign_members não tem
-- trigger, então o vínculo do dono é auditado MANUALMENTE na convenção da
-- migration 08 (acao='MEMBER_ADD', depois=jsonb_build_object('papel','escopo')).
-- Nenhuma auditoria manual é gerada no caminho idempotente. Tudo em UMA transação:
-- qualquer erro reverte inclusive as auditorias manuais.
-- ============================================================================
BEGIN;

create or replace function public.create_campaign_candidate_model(
  p_campaign_id    uuid,
  p_org            uuid,
  p_candidato_nome text,
  p_ano            smallint,
  p_cargo          text,
  p_nome_urna      text default null,
  p_uf             text default null,
  p_numero         text default null,
  p_partido        text default null,
  p_tipo_comercial text default 'doada',
  p_valor_texto    text default null,
  p_situacao       text default 'ativa',
  p_candidate_id   uuid default null
)
returns table (
  campaign_id           uuid,
  candidate_id          uuid,
  candidacy_id          uuid,
  member_id             uuid,
  candidate_reutilizado boolean,
  ja_existia            boolean
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid         uuid := auth.uid();
  v_dono        uuid;
  v_nome        text;
  v_cargo_norm  text;
  v_cargo_canon text;
  v_abrangencia text;
  v_uf          text;
  v_numero      text;
  v_partido     text;
  v_nome_urna   text;
  v_valor       text;
  -- persistidos (caminho idempotente)
  v_c           record;   -- campaigns
  v_cy          record;   -- candidacies
  v_cm          record;   -- candidacy_members principal
  v_cand_row    record;   -- candidates principal
  v_mem         record;   -- campaign_members do dono
  -- criação
  v_cand        uuid;
  v_candidacy   uuid;
  v_member      uuid;
  v_reuse       boolean := false;
  v_cand_del    timestamptz;
  v_cand_nome   text;
  v_camp_json   jsonb;
  v_campaign_member_user uuid;
  v_audit_campaign_id    bigint;
  v_audit_member_id      bigint;
begin
  -- 1. Autenticação e chave.
  if v_uid is null then
    raise exception 'Não autenticado.';
  end if;
  if p_campaign_id is null then
    raise exception 'p_campaign_id é obrigatório (UUID gerado pelo cliente).';
  end if;

  -- 2. Lock por transação sobre a chave, ANTES de qualquer consulta de existência.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_campaign_id::text, 0));

  -- 3. Organização e autorização (proprietário real). FOR UPDATE estabiliza a
  --    titularidade durante toda a transação.
  if p_org is null then
    raise exception 'Organização não informada.';
  end if;
  select o.dono_id into v_dono
    from public.organizations o
   where o.id = p_org
   for update;
  if not found then
    raise exception 'Organização inexistente.';
  end if;
  if v_dono is null then
    raise exception 'Organização sem proprietário.';
  end if;
  if v_dono is distinct from v_uid then
    raise exception 'Apenas o proprietário da organização pode criar a campanha.';
  end if;

  -- 4. Validação e normalização de TODOS os campos (as mesmas variáveis servem
  --    para comparar o payload no caminho idempotente e para o INSERT).
  if p_ano is null or p_ano < 1990 or p_ano > 2100 then
    raise exception 'Ano inválido: % (esperado entre 1990 e 2100).', p_ano;
  end if;
  if coalesce(p_tipo_comercial, '') not in ('doada','vendida') then
    raise exception 'Tipo comercial inválido: "%".', p_tipo_comercial;
  end if;
  if coalesce(p_situacao, '') not in ('ativa','suspensa','expirada') then
    raise exception 'Situação inválida: "%".', p_situacao;
  end if;

  v_nome := btrim(coalesce(p_candidato_nome, ''));
  if v_nome = '' then
    raise exception 'Nome do candidato é obrigatório.';
  end if;

  v_cargo_norm := lower(btrim(coalesce(p_cargo, '')));
  v_cargo_norm := regexp_replace(v_cargo_norm, '[ ./-]+', '_', 'g');
  v_cargo_norm := regexp_replace(v_cargo_norm, '_+', '_', 'g');
  v_cargo_norm := btrim(v_cargo_norm, '_');
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
    raise exception 'Cargo não reconhecido: "%". Informe um cargo canônico (presidente, governador, senador, deputado_federal, deputado_estadual, deputado_distrital, prefeito, vereador).', p_cargo;
  end if;

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

  if p_uf is null or btrim(p_uf) = '' then
    v_uf := null;
  else
    v_uf := upper(btrim(p_uf));
    if v_uf !~ '^[A-Z]{2}$' then
      raise exception 'UF inválida: "%".', p_uf;
    end if;
    if v_uf not in
      ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB',
       'PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO') then
      raise exception 'UF inválida: "%".', p_uf;
    end if;
  end if;
  if v_cargo_canon <> 'presidente' and v_uf is null then
    raise exception 'UF é obrigatória para o cargo %.', v_cargo_canon;
  end if;

  if p_numero is null or btrim(p_numero) = '' then
    v_numero := null;
  elsif btrim(p_numero) ~ '^[0-9]+$' then
    v_numero := btrim(p_numero);
  else
    raise exception 'Número inválido: "%" (apenas dígitos são aceitos).', p_numero;
  end if;

  v_partido   := upper(nullif(btrim(coalesce(p_partido, '')), ''));
  v_nome_urna := coalesce(nullif(btrim(coalesce(p_nome_urna, '')), ''), v_nome);
  v_valor     := nullif(btrim(coalesce(p_valor_texto, '')), '');

  -- 5. A campanha já existe? Carregada com FOR UPDATE num ÚNICO SELECT: o advisory
  --    lock serializa chamadas desta RPC; o FOR UPDATE bloqueia a linha contra
  --    alteração/exclusão direta por código externo durante toda a verificação.
  select c.* into v_c from public.campaigns c where c.id = p_campaign_id for update;
  if found then
    if v_c.org_id is distinct from p_org then
      raise exception 'Campanha já existe em outra organização.';
    end if;

    -- 5a. Estrutura completa (com FOR SHARE); ausência de qualquer parte = parcial.
    select cy.* into v_cy from public.candidacies cy
      where cy.campaign_id = p_campaign_id for share;
    if not found then
      raise exception 'Criação anterior parcial: campanha % existe sem candidatura.', p_campaign_id;
    end if;
    if v_cy.org_id is distinct from p_org then
      raise exception 'Inconsistência: candidatura de organização diferente da campanha.';
    end if;

    select cm.* into v_cm from public.candidacy_members cm
      where cm.candidacy_id = v_cy.id and cm.is_principal = true for share;
    if not found then
      raise exception 'Criação anterior parcial: candidatura % existe sem membro principal.', v_cy.id;
    end if;
    if v_cm.org_id is distinct from p_org then
      raise exception 'Inconsistência: composição de organização diferente.';
    end if;

    -- Candidato principal com FOR SHARE: existência, mesma org, não excluído e
    -- nome compatível são exigidos independentemente de p_candidate_id.
    select cand.* into v_cand_row from public.candidates cand
      where cand.id = v_cm.candidate_id for share;
    if not found then
      raise exception 'Criação anterior parcial: membro principal sem candidato.';
    end if;
    if v_cand_row.org_id is distinct from p_org then
      raise exception 'Inconsistência: candidato de organização diferente.';
    end if;
    if v_cand_row.deleted_at is not null then
      raise exception 'Criação anterior inconsistente: candidato principal está excluído.';
    end if;
    if btrim(coalesce(v_cand_row.nome_cadastro, '')) is distinct from v_nome then
      raise exception 'p_campaign_id já existe, mas os dados recebidos divergem da criação original.';
    end if;

    select m.* into v_mem from public.campaign_members m
      where m.campaign_id = p_campaign_id and m.user_id = v_uid for share;
    if not found then
      raise exception 'Criação anterior parcial: campanha sem campaign_member do proprietário.';
    end if;
    if v_mem.papel is distinct from 'admin' or v_mem.escopo is not null then
      raise exception 'Inconsistência: campaign_member do proprietário com papel/escopo inesperado.';
    end if;

    -- 5b. Comparar dados persistidos com os recalculados do payload atual.
    if v_c.org_id         is distinct from p_org
    or v_c.candidato_nome is distinct from v_nome
    or v_c.nome_urna      is distinct from v_nome_urna
    or v_c.cargo          is distinct from p_cargo
    or v_c.uf             is distinct from v_uf
    or v_c.numero         is distinct from v_numero
    or v_c.partido        is distinct from v_partido
    or v_c.tipo_comercial is distinct from p_tipo_comercial
    or v_c.valor_texto    is distinct from v_valor
    or v_c.situacao       is distinct from p_situacao
    or v_c.criada_por     is distinct from v_uid then
      raise exception 'p_campaign_id já existe, mas os dados recebidos divergem da criação original.';
    end if;
    if v_cy.nome_urna             is distinct from v_nome_urna
    or v_cy.ano                   is distinct from p_ano
    or v_cy.cargo                 is distinct from v_cargo_canon
    or v_cy.abrangencia           is distinct from v_abrangencia
    or v_cy.uf                    is distinct from v_uf
    or v_cy.numero                is distinct from v_numero
    or v_cy.sigla_partido_disputa is distinct from v_partido then
      raise exception 'p_campaign_id já existe, mas os dados recebidos divergem da criação original.';
    end if;
    if v_cm.papel is distinct from 'titular'
    or v_cm.ordem is distinct from 1
    or v_cm.is_principal is distinct from true then
      raise exception 'Inconsistência: membro principal com papel/ordem inesperados.';
    end if;
    -- Se p_candidate_id foi informado, deve ser exatamente o principal persistido.
    -- (O nome já foi validado acima, para os dois casos — sem verificação redundante.)
    if p_candidate_id is not null and v_cand_row.id is distinct from p_candidate_id then
      raise exception 'p_campaign_id já existe, mas os dados recebidos divergem da criação original.';
    end if;

    campaign_id           := p_campaign_id;
    candidate_id          := v_cand_row.id;
    candidacy_id          := v_cy.id;
    member_id             := v_cm.id;
    -- Limite documentado: não há coluna que registre a origem histórica do
    -- candidato numa repetição; usa-se regra determinística compatível com o
    -- payload (p_candidate_id informado ⇒ true). Não afirma origem histórica.
    candidate_reutilizado := (p_candidate_id is not null);
    ja_existia            := true;
    return next;
    return;
  end if;

  -- 6. CRIAÇÃO. campaigns (legado preservado; cargo legado = valor recebido).
  insert into public.campaigns as c (
    id, org_id, candidato_nome, nome_urna, cargo, uf, numero, partido,
    tipo_comercial, valor_texto, situacao, criada_por
  ) values (
    p_campaign_id, p_org, v_nome, v_nome_urna, p_cargo, v_uf, v_numero, v_partido,
    p_tipo_comercial, v_valor, p_situacao, v_uid
  )
  returning to_jsonb(c) into v_camp_json;
  if v_camp_json is null then
    raise exception 'Falha ao inserir a campanha.';
  end if;

  -- 6a. Auditoria manual do INSERT de campaigns (trigger da 03 só cobre UPDATE/DELETE).
  insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (p_campaign_id, v_uid, 'INSERT', 'campaigns', p_campaign_id::text, null, v_camp_json)
  returning id into v_audit_campaign_id;
  if v_audit_campaign_id is null then
    raise exception 'Falha ao auditar a criação da campanha.';
  end if;

  -- 7. Candidato: novo ou reutilizado (mesma org, não excluído). Sem dedup por nome.
  if p_candidate_id is null then
    insert into public.candidates (org_id, user_id, nome_cadastro, identidade_confirmada)
    values (p_org, null, v_nome, false)
    returning id into v_cand;
    if v_cand is null then
      raise exception 'Falha ao inserir o candidato.';
    end if;
    v_reuse := false;
  else
    -- FOR SHARE: impede exclusão/alteração do candidato por outra transação
    -- durante esta criação, sem exigir bloqueio exclusivo (não escrevemos nele).
    select cand.deleted_at, cand.nome_cadastro into v_cand_del, v_cand_nome
      from public.candidates cand
     where cand.id = p_candidate_id and cand.org_id = p_org
     for share;
    if not found then
      raise exception 'Candidato inexistente nesta organização.';
    end if;
    if v_cand_del is not null then
      raise exception 'Candidato excluído não pode ser reutilizado.';
    end if;
    if btrim(coalesce(v_cand_nome, '')) is distinct from v_nome then
      raise exception 'Nome informado difere da identidade do candidato reutilizado.';
    end if;
    v_cand  := p_candidate_id;
    v_reuse := true;
  end if;

  -- 8. Candidatura (campaign_id preenchido; permitido por ser função definer).
  insert into public.candidacies (
    org_id, campaign_id, nome_urna, ano, cargo, uf, numero, sigla_partido_disputa, abrangencia
  ) values (
    p_org, p_campaign_id, v_nome_urna, p_ano, v_cargo_canon, v_uf, v_numero, v_partido, v_abrangencia
  )
  returning id into v_candidacy;
  if v_candidacy is null then
    raise exception 'Falha ao inserir a candidatura.';
  end if;

  -- 9. Composição: titular e principal.
  insert into public.candidacy_members (org_id, candidacy_id, candidate_id, papel, ordem, is_principal)
  values (p_org, v_candidacy, v_cand, 'titular', 1, true)
  returning id into v_member;
  if v_member is null then
    raise exception 'Falha ao inserir a composição da candidatura.';
  end if;

  -- 10. Vínculo do proprietário em campaign_members (preserva o fluxo atual).
  --     PK real é (campaign_id, user_id); confere-se o user_id retornado.
  insert into public.campaign_members (campaign_id, user_id, papel)
  values (p_campaign_id, v_uid, 'admin')
  returning user_id into v_campaign_member_user;
  if v_campaign_member_user is null or v_campaign_member_user is distinct from v_uid then
    raise exception 'Falha ao criar o vínculo administrativo da campanha.';
  end if;

  -- 10a. Auditoria manual do membro (convenção da migration 08; sem trigger).
  insert into public.audit_log(campaign_id, user_id, acao, entidade, entidade_id, antes, depois)
  values (p_campaign_id, v_uid, 'MEMBER_ADD', 'campaign_members', v_uid::text,
          null, jsonb_build_object('papel', 'admin', 'escopo', null))
  returning id into v_audit_member_id;
  if v_audit_member_id is null then
    raise exception 'Falha ao auditar o vínculo administrativo da campanha.';
  end if;

  campaign_id           := p_campaign_id;
  candidate_id          := v_cand;
  candidacy_id          := v_candidacy;
  member_id             := v_member;
  candidate_reutilizado := v_reuse;
  ja_existia            := false;
  return next;
end;
$$;

revoke all on function public.create_campaign_candidate_model(
  uuid, uuid, text, smallint, text, text, text, text, text, text, text, text, uuid
) from public, anon;
grant execute on function public.create_campaign_candidate_model(
  uuid, uuid, text, smallint, text, text, text, text, text, text, text, text, uuid
) to authenticated;

COMMIT;

-- ============================================================================
-- TESTES A EXECUTAR APÓS APLICAR A 12 (não executados aqui):
--  1.  proprietário cria campanha com candidato novo (todos os registros criados).
--  2.  candidato novo permanece com user_id NULL.
--  3.  proprietário cria campanha reutilizando candidato da mesma org (candidate_reutilizado=true).
--  4.  candidato de outra org é negado.
--  5.  candidato inexistente é negado.
--  6.  usuário não proprietário é negado.
--  7.  membro/admin de campanha sem propriedade da org é negado.
--  8.  anon não pode executar (sem EXECUTE).
--  9.  campaign, candidacy e member recebem a mesma org.
--  10. campaign_id fica vinculado em candidacies.
--  11. titular principal é criado (papel='titular', ordem=1, is_principal=true).
--  12. segunda chamada com mesmo p_campaign_id e payload idêntico retorna ja_existia=true.
--  13. segunda chamada retorna os mesmos UUIDs.
--  14. duplo clique não cria duplicatas (advisory lock + PK/UNIQUE).
--  15. chamada concorrente com mesmo p_campaign_id não cria duplicatas.
--  16. criação parcial preexistente (campanha sem candidatura/membro) gera erro.
--  17. cargo "Dep. Federal" normaliza para deputado_federal em candidacies.
--  18. abrangência de deputado_federal vira 'estadual'.
--  19. UF "sc" normaliza para "SC".
--  20. UF "SCC" é rejeitada (sem truncamento).
--  21. UF "XX" é rejeitada.
--  22. número com letras é rejeitado.
--  23. número com zeros à esquerda é preservado.
--  24. presidente aceita UF nula.
--  25. demais cargos exigem UF.
--  26. nome de urna vazio usa nome_cadastro (fallback).
--  27. campos legados de campaigns permanecem preenchidos (cargo recebido, etc.).
--  28. auditoria é criada para candidates/candidacies/candidacy_members (triggers da 10).
--  29. erro no último INSERT desfaz todos os anteriores (rollback).
--  30. a campanha real já existente NÃO é alterada por esta função.
--  31. mesmo campaign_id e payload idêntico retorna ja_existia=true.
--  32. mesmo campaign_id com ano diferente é negado (divergência).
--  33. mesmo campaign_id com cargo diferente é negado.
--  34. mesmo campaign_id com UF diferente é negado.
--  35. mesmo campaign_id com número diferente é negado.
--  36. mesmo campaign_id com partido diferente é negado.
--  37. mesmo campaign_id com candidate_id diferente é negado.
--  38. mesmo campaign_id com organização diferente é negado.
--  39. campaign existente sem campaign_member do dono é denunciada como parcial.
--  40. campaign_member do dono com papel/escopo incorreto é denunciado.
--  41. candidato reutilizado é bloqueado (FOR SHARE) durante a transação.
--  42. nome informado divergente do candidato reutilizado é negado.
--  43. INSERT de campaigns gera exatamente uma auditoria (acao='INSERT').
--  44. repetição idempotente NÃO duplica auditoria de campaigns.
--  45. criação do campaign_member gera auditoria MEMBER_ADD (convenção da 08).
--  46. repetição idempotente NÃO duplica auditoria do membro.
--  47. erro posterior desfaz também as auditorias manuais (mesma transação).
--  48. campanha existente é bloqueada (FOR UPDATE) durante a verificação idempotente.
--  49. alteração direta concorrente em campaigns aguarda o término da RPC.
--  50. candidato principal excluído impede retorno idempotente.
--  51. candidato principal com nome divergente impede retorno idempotente.
--  52. candidato principal é bloqueado com FOR SHARE no caminho idempotente.
--  53. candidatura, composição e campaign_member são bloqueados (FOR SHARE) na leitura idempotente.
--  54. INSERT de campaign_members confirma o user_id retornado.
--  55. auditoria de campaigns confirma o id retornado.
--  56. auditoria MEMBER_ADD confirma o id retornado.
--  57. falha em qualquer RETURNING desfaz toda a criação.
-- ============================================================================
