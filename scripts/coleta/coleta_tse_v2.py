#!/usr/bin/env python3
"""Coleta e filtragem de dados TSE 2022 para Santa Catarina.
URLs corrigidas após verificação no CKAN dadosabertos.tse.jus.br.
"""

import os, io, zipfile, requests, pandas as pd

RAW_TSE = "/home/user/workspace/sc-inteligencia/raw/tse"

# ─────────────────────────────────────────────────────────────────
# TAREFAS 1 e 2: Votação candidato munzona (arquivo NACIONAL)
# ─────────────────────────────────────────────────────────────────
URL_VOT = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"
print(f"[TSE] Baixando {URL_VOT}  (~557 MB) ...")
resp = requests.get(URL_VOT, timeout=600, stream=False)
print(f"[TSE] Status: {resp.status_code} | Tamanho: {len(resp.content):,} bytes")

with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
    names = zf.namelist()
    print(f"[TSE] Arquivos no ZIP: {names}")
    csv_name = [n for n in names if n.lower().endswith('.csv')][0]
    with zf.open(csv_name) as f:
        # Ler apenas linhas de SC para economizar memória
        df = pd.read_csv(f, sep=';', encoding='latin-1', dtype=str, low_memory=False)

print(f"[TSE] Total registros nacional: {len(df):,}")
print(f"[TSE] Colunas: {list(df.columns)[:10]} ...")

# Filtrar apenas SC
df_sc = df[df['SG_UF'] == 'SC'].copy()
print(f"[TSE] Registros SC: {len(df_sc):,}")
print(f"[TSE] Cargos em SC: {sorted(df_sc['DS_CARGO'].unique().tolist())}")

# Tarefa 1 — Deputado Federal
dep_fed = df_sc[df_sc['DS_CARGO'] == 'DEPUTADO FEDERAL'].copy()
out1 = os.path.join(RAW_TSE, 'votacao_dep_federal_sc_2022.csv')
dep_fed.to_csv(out1, sep=';', index=False, encoding='utf-8')
print(f"[TSE] DEPUTADO FEDERAL: {len(dep_fed):,} registros → {out1}")

# Tarefa 2a — Governador
gov = df_sc[df_sc['DS_CARGO'] == 'GOVERNADOR'].copy()
out2a = os.path.join(RAW_TSE, 'votacao_governador_sc_2022.csv')
gov.to_csv(out2a, sep=';', index=False, encoding='utf-8')
print(f"[TSE] GOVERNADOR: {len(gov):,} registros → {out2a}")

# Tarefa 2b — Senador
sen = df_sc[df_sc['DS_CARGO'] == 'SENADOR'].copy()
out2b = os.path.join(RAW_TSE, 'votacao_senador_sc_2022.csv')
sen.to_csv(out2b, sep=';', index=False, encoding='utf-8')
print(f"[TSE] SENADOR: {len(sen):,} registros → {out2b}")

# Liberar memória
del df, df_sc

# ─────────────────────────────────────────────────────────────────
# TAREFA 3: Perfil do eleitorado 2022 (arquivo nacional, 44 MB)
# Filtrar SG_UF == 'SC'
# ─────────────────────────────────────────────────────────────────
URL_EL = "https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitorado/perfil_eleitorado_2022.zip"
print(f"\n[ELEITORADO] Baixando {URL_EL}  (~44 MB) ...")
resp_el = requests.get(URL_EL, timeout=300)
print(f"[ELEITORADO] Status: {resp_el.status_code} | Tamanho: {len(resp_el.content):,} bytes")

with zipfile.ZipFile(io.BytesIO(resp_el.content)) as zf2:
    names2 = zf2.namelist()
    print(f"[ELEITORADO] Arquivos no ZIP: {names2}")
    csv_name2 = [n for n in names2 if n.lower().endswith('.csv')][0]
    with zf2.open(csv_name2) as f2:
        df_el = pd.read_csv(f2, sep=';', encoding='latin-1', dtype=str, low_memory=False)

print(f"[ELEITORADO] Total nacional: {len(df_el):,}")
print(f"[ELEITORADO] Colunas: {list(df_el.columns)[:10]} ...")

# Detectar coluna UF (pode variar)
uf_col = next((c for c in df_el.columns if 'SG_UF' in c or c == 'UF'), None)
print(f"[ELEITORADO] Coluna UF detectada: {uf_col}")
if uf_col:
    df_el_sc = df_el[df_el[uf_col] == 'SC'].copy()
else:
    # Tentar coluna genérica
    df_el_sc = df_el[df_el.apply(lambda r: 'SC' in r.values, axis=1)].copy()

out3 = os.path.join(RAW_TSE, 'eleitorado_sc_2022.csv')
df_el_sc.to_csv(out3, sep=';', index=False, encoding='utf-8')
print(f"[ELEITORADO] SC: {len(df_el_sc):,} registros → {out3}")

print("\n[TSE] Coleta concluída.")
