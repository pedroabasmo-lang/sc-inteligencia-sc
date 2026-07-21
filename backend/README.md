# Backend Fase A — como colocar no ar

Objetivo: tirar os apoiadores do navegador e pôr num banco seguro (Supabase),
com login, isolamento por campanha (RLS), controle comercial por candidato e LGPD.

## Passo 1 — criar o projeto Supabase (grátis, ~5 min)

1. Acesse https://supabase.com e crie conta (pode usar o Google).
2. "New project" → dê um nome (ex.: `henrichs`), escolha região **South America (São Paulo)**, defina uma senha de banco (guarde) e crie.
3. Espere ~2 min o projeto subir.

## Passo 2 — criar as tabelas

1. No projeto, menu lateral → **SQL Editor** → **New query**.
2. Abra o arquivo `backend/01_schema_fase_a.sql`, copie TODO o conteúdo, cole no editor.
3. Clique **Run**. Deve terminar sem erro ("Success").

## Passo 3 — pegar as chaves de conexão

1. Menu → **Project Settings** → **API**.
2. Copie dois valores:
   - **Project URL** (ex.: `https://abcd.supabase.co`)
   - **anon public** key (uma chave longa que começa com `eyJ...`)
3. Abra `painel/campanha.html`, no topo do `<script>` cole os dois em `SUPABASE_URL` e `SUPABASE_ANON`.

> A chave **anon** pode ficar no frontend — é pública por design. A segurança real está
> na RLS do banco (Passo 2), não na chave. NUNCA use a chave `service_role` no frontend.

## Passo 4 — criar seu usuário e sua consultoria

1. Abra `painel/campanha.html` no navegador (pelo servidor local, como o painel).
2. "Criar conta" com seu e-mail e senha.
3. No primeiro acesso, crie a **organização** (sua consultoria).
4. Crie a primeira **campanha** (um candidato), definindo se é doada ou vendida e o valor.
5. Cadastre apoiadores — agora salvos no banco, com consentimento e trilha de auditoria.

## O que isto resolve (da crítica)

- Apoiadores saem do `localStorage` → banco com RLS: campanha de um candidato **nunca** vaza para outro.
- Login real (Supabase Auth).
- LGPD: base legal, consentimento, canais autorizados, exclusão lógica (descadastramento) e **auditoria automática** (quem inseriu/alterou/excluiu, quando).
- Controle comercial por campanha: doada/vendida, valor livre por candidato, ativa/suspensa — cobrança feita por você, por fora; o sistema só libera/corta o acesso.

## Próximas fases

- **B**: financeiro no padrão prestação de contas + exportação Conta+JE.
- **C**: migrar os demais módulos (agenda, equipes, materiais…) e Dia D offline (PWA).
- Onboarding com perfil do candidato como configurador (municípios prioritários).

O painel de dados públicos (`index.html`) continua estático e independente — não muda.
