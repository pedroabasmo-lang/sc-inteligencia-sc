# raw/ — Dados Brutos Coletados das APIs

Coletado em: 2026-04-22
Total: 17 fontes consultadas

## Inventário por fonte

### IBGE
- `ibge/municipios_sc.json` — 295 municípios SC (id, nome, hierarquia)
- `ibge/populacao_sc.json` — população 2022 (Censo)
- `ibge/pib_sc.json` — PIB municipal 2021

### BrasilAPI / STN
- `brasilapi/cnpj_prefeituras_sc.json` — CNPJs das 295 prefeituras SC
- `brasilapi/siconfi_entes_sc.json` — entes municipais SC (fonte SICONFI)

### Câmara dos Deputados
- `camara/deputados_sc.json` — 21 deputados federais SC (legislatura 57)
- `camara/perfis_deputados_sc.json` — perfis completos dos 21 deputados
- `camara/emendas_deputados_sc.json` — 1.411 emendas EMC dos deputados SC
- `camara/ceap_sc_2024.json` — 2.000 lançamentos de cota parlamentar 2024

### Senado Federal
- `senado/senadores_sc.json` — 3 senadores SC (Amin/PP, Ivete/MDB, Seif/PL)
- `senado/emendas_senadores_sc.json` — endpoint /orcamento retornou 404 (registrado)

### Portal da Transparência
- `transparencia/emendas_sc_2020.json` — 204 emendas
- `transparencia/emendas_sc_2021.json` — 173 emendas
- `transparencia/emendas_sc_2022.json` — 156 emendas
- `transparencia/emendas_sc_2023.json` — 215 emendas
- `transparencia/emendas_sc_2024.json` — 125 emendas
- `transparencia/emendas_sem_municipio_sc.json` — 730 emendas com destino UF/Múltiplo (sem município)

### TransfereGov (PostgREST)
- `transferegov/plano_acao_sc.json` — 3.601 planos de ação SC
- `transferegov/plano_acao_por_dep_sc.json` — 1.304 planos filtrados por parlamentar SC
- `transferegov/convenios_sc.json` — 1.318 convênios/fundo a fundo SC
- `transferegov/empenhos_sc.json` — 3.640 empenhos especiais SC

### FNS (Fundo Nacional de Saúde)
- `fns/repasses_sc.json` — DNS não resolve (rede interna MS); registrado
- `fns/emenda_uczai_teste.json` — mesmo diagnóstico

### FNDE
- `fnde/pnae_sc.json` — 295 municípios SC, programa PNAE identificado
- `fnde/pdde_sc.json` — 295 municípios SC, 4 modalidades PDDE

### STN / Tesouro Transparente
- `stn/fpm_sc_2024.json` — FPM 2024: 3.540 registros (295 × 12 meses), R$6,87B
- `stn/cide_sc_2024.json` — CIDE 2024: 3.540 registros, R$9,33M

### MDS / Bolsa Família
- `mds/bolsa_familia_sc.json.gz` — ~232k famílias/mês 2024; R$161,9M/jan2024

### SICONFI
- `siconfi/dca_sc_2023.json.gz` — 332.301 registros balanço contábil 2023
- `siconfi/dca_sc_2022_all.json.gz` — 319.018 registros balanço contábil 2022
- `siconfi/rgf_sc_2024.json` — tabela RGF vazia na API (registrado)

### SEF-SC (dados.sc.gov.br CKAN)
- `sef_sc/arrecadacao_icms_ipva_municipios_sc_2022.csv` — 13.261 registros
- `sef_sc/arrecadacao_setor_economico_sc_2022.csv` — 7.961 registros

### TSE 2022
- `tse/votacao_dep_federal_sc_2022.csv.gz` — 91.688 registros
- `tse/votacao_governador_sc_2022.csv` — 3.768 registros
- `tse/votacao_senador_sc_2022.csv` — 2.826 registros
- `tse/eleitorado_sc_2022.csv.gz` — 201.808 registros

### Transparência SC
- `transparencia_sc/status_endpoints.json` — SPA Angular, sem API pública

### DATASUS
- `datasus/status_endpoints.json` — endpoint /financiamento/repasses não existe na versão atual

### DOU (Diário Oficial da União)
- `dou/resumo_endpoints.json` — 13 endpoints testados, todos retornam HTML ou exigem login INLABS
- `dou/querido_diario_emenda_sc_filtrado.json` — dados do Querido Diário (diários municipais)

## Endpoints não disponíveis publicamente
| Fonte | Motivo |
|-------|--------|
| FNS API | DNS não resolve (rede interna MS) |
| DOU/INLABS | Requer cadastro em inlabs.in.gov.br |
| Senado /orcamento | Endpoint 404 — emendas em SIOP/LOA |
| DATASUS /financiamento | Rota não existe na API DEMAS atual |
| RGF SICONFI | Tabela vazia na API pública |
