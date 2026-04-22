#!/usr/bin/env python3
"""
Coleta complementar TransfereGov SC:
- Fundo a Fundo (plano_acao) para SC  → substitui a tarefa 3 de convênios (REST 404)
- Tenta endpoint REST de convênios com variações conhecidas
"""

import requests
import json
import time
import os
from datetime import datetime

BASE_DIR = "/home/user/workspace/sc-inteligencia/raw/transferegov"
SLEEP_BETWEEN = 0.5

HEADERS = {"Accept": "application/json"}


def fetch_postgrest_paginated(url_base, params_base, label="endpoint"):
    all_records = []
    offset = 0
    page = 0
    while True:
        params = dict(params_base)
        params["limit"] = 1000
        params["offset"] = offset
        print(f"  [{label}] Página {page+1} | offset={offset} ...")
        try:
            resp = requests.get(url_base, headers=HEADERS, params=params, timeout=60)
            print(f"    Status: {resp.status_code}")
            if resp.status_code == 406:
                resp = requests.get(url_base, params=params, timeout=60)
                print(f"    Status (sem header): {resp.status_code}")
            if resp.status_code != 200:
                print(f"    [ERRO] {resp.status_code}: {resp.text[:200]}")
                break
            data = resp.json()
            if not data:
                print(f"    Lista vazia, paginação encerrada.")
                break
            print(f"    Recebidos {len(data)} registros.")
            all_records.extend(data)
            if len(data) < 1000:
                break
            offset += 1000
            page += 1
        except Exception as e:
            print(f"    [EXCEPTION] {e}")
            break
        time.sleep(SLEEP_BETWEEN)
    return all_records


def save_json(data, filepath, metadata=None):
    payload = {
        "metadata": metadata or {},
        "total_records": len(data) if isinstance(data, list) else "N/A",
        "collected_at": datetime.now().isoformat() + "Z",
        "data": data
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  [SALVO] {filepath} ({payload['total_records']} registros)")


# =============================================================================
# TAREFA 3 (alternativa) — Fundo a Fundo plano_acao SC
# =============================================================================
print("\n" + "="*60)
print("TAREFA 3 (alt): Fundo a Fundo - Planos de ação SC")
print("="*60)

url_ff = "https://api.transferegov.gestao.gov.br/fundoafundo/plano_acao"

# SC como recebedor
params_ff_recebedor = {"uf_ente_recebedor_plano_acao": "eq.SC"}
faf_recebedor = fetch_postgrest_paginated(url_ff, params_ff_recebedor, label="faf_recebedor_SC")

# SC como repassador (menos comum mas possível)
params_ff_repassador = {"uf_ente_repassador_plano_acao": "eq.SC"}
faf_repassador = fetch_postgrest_paginated(url_ff, params_ff_repassador, label="faf_repassador_SC")

all_faf = faf_recebedor + faf_repassador
save_json(
    all_faf,
    os.path.join(BASE_DIR, "convenios_sc.json"),
    metadata={
        "source": "PostgREST /fundoafundo/plano_acao",
        "note": "REST /convenios/convenios retornou 404 — substituído por fundo_a_fundo/plano_acao",
        "filters_used": [
            "uf_ente_recebedor_plano_acao=eq.SC",
            "uf_ente_repassador_plano_acao=eq.SC"
        ],
        "faf_recebedor_count": len(faf_recebedor),
        "faf_repassador_count": len(faf_repassador)
    }
)

# =============================================================================
# BÔNUS: Empenhos SC (transferencias especiais)
# =============================================================================
print("\n" + "="*60)
print("BÔNUS: Empenhos SC (Transferências Especiais)")
print("="*60)

url_emp = "https://api.transferegov.gestao.gov.br/transferenciasespeciais/empenho_especial"
params_emp = {"uf_beneficiario_empenho": "eq.SC"}
empenhos_sc = fetch_postgrest_paginated(url_emp, params_emp, label="empenho_SC")

save_json(
    empenhos_sc,
    os.path.join(BASE_DIR, "empenhos_sc.json"),
    metadata={
        "source": "PostgREST /transferenciasespeciais/empenho_especial",
        "filter": "uf_beneficiario_empenho=eq.SC"
    }
)

# =============================================================================
# RESUMO
# =============================================================================
print("\n" + "="*60)
print("RESUMO COLETA COMPLEMENTAR")
print("="*60)
print(f"  Fundo a Fundo SC (recebedor): {len(faf_recebedor):>8} registros")
print(f"  Fundo a Fundo SC (repassador):{len(faf_repassador):>8} registros")
print(f"  Total convenios_sc.json:      {len(all_faf):>8} registros")
print(f"  Empenhos SC:                  {len(empenhos_sc):>8} registros")
print("="*60)
