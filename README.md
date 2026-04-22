# sc-inteligencia

Sistema de inteligência eleitoral-orçamentária para Santa Catarina.

Cruza três eixos por município: **votação** (TSE 2022/2024), **emendas recebidas** (Portal da Transparência + TransfereGov + FNS) e **aliança partidária** do prefeito.

## Quick Start

```bash
# 1. Clone e instale
git clone https://github.com/SEU_USUARIO/sc-inteligencia
cd sc-inteligencia
pip install -e .

# 2. Configure variáveis
cp .env.example .env
# Preencha PORTAL_TRANSPARENCIA_API_KEY
# Obtenha em: https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email

# 3. Bootstrap (baixa municípios IBGE, inicializa DuckDB)
python -m scripts.bootstrap

# 4. Primeira ingestão (SC, fase 1)
python -m scripts.run_mensal --fase 1 --uf SC
```

## Variáveis de Ambiente

| Variável | Obrigatório | Descrição |
|---|---|---|
| PORTAL_TRANSPARENCIA_API_KEY | SIM | Chave da API do Portal da Transparência |
| TRANSFEREGOV_TOKEN | NÃO | Token Bearer do TransfereGov (dados extras) |
| DUCKDB_PATH | NÃO | Path do DuckDB (default: unified/warehouse.duckdb) |

## Arquitetura

```
Portal da Transparência → emendas brutas
     ↓ (se destino=UF/Múltiplo)
TransfereGov API → convênios e transferências especiais por município
     ↓ (se função=10-Saúde e sem resultado)
FNS API → repasses fundo-a-fundo por portaria
     ↓ (se nada resolver)
match_log: granularidade_perdida=True
```

## Limitações Conhecidas

1. **Emendas UF-level**: ~30% das emendas têm destino "UF" ou "Múltiplo" no Portal da Transparência. O sistema tenta resolver via TransfereGov e FNS, mas alguns valores permanecem em nível estadual.
2. **API TransfereGov**: endpoints sujeitos a mudança de versão. Se retornar 404, verificar swagger em https://api.transferegov.gestao.gov.br/swagger-ui.html
3. **Aliases TSE**: nomes de candidatos no TSE diferem dos nomes na Câmara. Manter `lookups/aliases_municipio.csv` atualizado.
4. **RP-9 inconstitucional**: emendas de relator (RP-9) declaradas inconstitucionais pelo STF em 2022, mas ainda aparecem nos dados históricos. Marcadas com flag `rp9_inconstitucional=True`.

## Match Log

Toda decisão de resolução de emenda → município é registrada em `unified/match_log.parquet`:

```python
import pandas as pd
df = pd.read_parquet("unified/match_log.parquet")
# Ver emendas não resolvidas
nao_resolvidas = df[df["tipo_match"] == "nao_resolvido"]
```
