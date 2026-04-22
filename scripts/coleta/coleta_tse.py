#!/usr/bin/env python3
"""Coleta e filtragem de dados TSE 2022 para Santa Catarina."""

import os
import io
import zipfile
import requests
import pandas as pd
import tempfile

RAW_TSE = "/home/user/workspace/sc-inteligencia/raw/tse"

# ──────────────────────────────────────────────
# TAREFAS 1 e 2: Votação candidato munzona SC
# ──────────────────────────────────────────────
URL_VOT = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022_SC.zip"

print(f"[TSE] Baixando {URL_VOT} ...")
resp = requests.get(URL_VOT, timeout=300)
print(f"[TSE] Status HTTP: {resp.status_code} | Tamanho: {len(resp.content):,} bytes")

with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
    names = zf.namelist()
    print(f"[TSE] Arquivos no ZIP: {names}")
    # Ler o CSV principal (normalmente o único arquivo CSV)
    csv_name = [n for n in names if n.lower().endswith('.csv')][0]
    with zf.open(csv_name) as f:
        df = pd.read_csv(f, sep=';', encoding='latin-1', dtype=str, low_memory=False)

print(f"[TSE] Total de registros no arquivo original: {len(df):,}")
print(f"[TSE] Colunas: {list(df.columns)}")
print(f"[TSE] Cargos únicos: {df['DS_CARGO'].unique().tolist()}")

# Tarefa 1 — Deputado Federal
dep_fed = df[df['DS_CARGO'] == 'DEPUTADO FEDERAL'].copy()
out1 = os.path.join(RAW_TSE, 'votacao_dep_federal_sc_2022.csv')
dep_fed.to_csv(out1, sep=';', index=False, encoding='utf-8')
print(f"[TSE] DEPUTADO FEDERAL: {len(dep_fed):,} registros → {out1}")

# Tarefa 2a — Governador
gov = df[df['DS_CARGO'] == 'GOVERNADOR'].copy()
out2a = os.path.join(RAW_TSE, 'votacao_governador_sc_2022.csv')
gov.to_csv(out2a, sep=';', index=False, encoding='utf-8')
print(f"[TSE] GOVERNADOR: {len(gov):,} registros → {out2a}")

# Tarefa 2b — Senador
sen = df[df['DS_CARGO'] == 'SENADOR'].copy()
out2b = os.path.join(RAW_TSE, 'votacao_senador_sc_2022.csv')
sen.to_csv(out2b, sep=';', index=False, encoding='utf-8')
print(f"[TSE] SENADOR: {len(sen):,} registros → {out2b}")

# ──────────────────────────────────────────────
# TAREFA 3: Perfil eleitorado 2022 (nacional) → filtrar SC
# ──────────────────────────────────────────────
URL_EL = "https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitorado/perfil_eleitorado_2022.zip"

print(f"\n[ELEITORADO] Baixando {URL_EL} ...")
resp_el = requests.get(URL_EL, timeout=600)
print(f"[ELEITORADO] Status HTTP: {resp_el.status_code} | Tamanho: {len(resp_el.content):,} bytes")

with zipfile.ZipFile(io.BytesIO(resp_el.content)) as zf2:
    names2 = zf2.namelist()
    print(f"[ELEITORADO] Arquivos no ZIP: {names2}")
    csv_name2 = [n for n in names2 if n.lower().endswith('.csv')][0]
    with zf2.open(csv_name2) as f2:
        df_el = pd.read_csv(f2, sep=';', encoding='latin-1', dtype=str, low_memory=False)

print(f"[ELEITORADO] Total de registros nacional: {len(df_el):,}")
print(f"[ELEITORADO] Colunas: {list(df_el.columns)}")

# Filtrar SC
df_el_sc = df_el[df_el['SG_UF'] == 'SC'].copy()
out3 = os.path.join(RAW_TSE, 'eleitorado_sc_2022.csv')
df_el_sc.to_csv(out3, sep=';', index=False, encoding='utf-8')
print(f"[ELEITORADO] SC: {len(df_el_sc):,} registros → {out3}")

print("\n[TSE] Coleta concluída.")
