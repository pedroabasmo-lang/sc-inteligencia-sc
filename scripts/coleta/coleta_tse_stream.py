#!/usr/bin/env python3
"""Coleta TSE 2022 — streaming download para disco, depois filtro SC."""

import os, io, zipfile, requests, pandas as pd

RAW_TSE = "/home/user/workspace/sc-inteligencia/raw/tse"
TMP_ZIP = "/home/user/workspace/sc-inteligencia/raw/tse/votacao_candidato_munzona_2022.zip"

URL_VOT = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"

# Download em streaming
if not os.path.exists(TMP_ZIP):
    print(f"[TSE] Iniciando download streaming de {URL_VOT} ...")
    with requests.get(URL_VOT, stream=True, timeout=600) as r:
        r.raise_for_status()
        total = 0
        with open(TMP_ZIP, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8*1024*1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
                    print(f"  Baixado: {total/1e6:.1f} MB", flush=True)
    print(f"[TSE] Download concluído: {os.path.getsize(TMP_ZIP):,} bytes")
else:
    print(f"[TSE] Arquivo já existe: {os.path.getsize(TMP_ZIP):,} bytes")

# Extrair e filtrar
print("[TSE] Extraindo CSV do ZIP ...")
with zipfile.ZipFile(TMP_ZIP) as zf:
    names = zf.namelist()
    print(f"[TSE] Arquivos no ZIP: {names}")
    csv_name = [n for n in names if n.lower().endswith('.csv')][0]
    
    # Leitura em chunks para economizar RAM
    print("[TSE] Lendo CSV em chunks (filtro SG_UF == SC) ...")
    chunks_sc = []
    with zf.open(csv_name) as f:
        reader = pd.read_csv(f, sep=';', encoding='latin-1', dtype=str,
                             low_memory=False, chunksize=200_000)
        for i, chunk in enumerate(reader):
            sc_chunk = chunk[chunk['SG_UF'] == 'SC']
            if len(sc_chunk) > 0:
                chunks_sc.append(sc_chunk)
            print(f"  Chunk {i}: {len(chunk):,} linhas → {len(sc_chunk):,} SC", flush=True)

df_sc = pd.concat(chunks_sc, ignore_index=True)
print(f"[TSE] Total SC: {len(df_sc):,}")
print(f"[TSE] Cargos: {sorted(df_sc['DS_CARGO'].unique().tolist())}")

# Salvar filtrados
dep_fed = df_sc[df_sc['DS_CARGO'] == 'DEPUTADO FEDERAL']
gov = df_sc[df_sc['DS_CARGO'] == 'GOVERNADOR']
sen = df_sc[df_sc['DS_CARGO'] == 'SENADOR']

out1 = os.path.join(RAW_TSE, 'votacao_dep_federal_sc_2022.csv')
out2a = os.path.join(RAW_TSE, 'votacao_governador_sc_2022.csv')
out2b = os.path.join(RAW_TSE, 'votacao_senador_sc_2022.csv')

dep_fed.to_csv(out1, sep=';', index=False, encoding='utf-8')
gov.to_csv(out2a, sep=';', index=False, encoding='utf-8')
sen.to_csv(out2b, sep=';', index=False, encoding='utf-8')

print(f"[TSE] DEPUTADO FEDERAL: {len(dep_fed):,} → {out1}")
print(f"[TSE] GOVERNADOR: {len(gov):,} → {out2a}")
print(f"[TSE] SENADOR: {len(sen):,} → {out2b}")
print("[TSE] Tarefas 1+2 concluídas.")
