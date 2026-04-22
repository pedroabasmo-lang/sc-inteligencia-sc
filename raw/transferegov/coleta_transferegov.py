#!/usr/bin/env python3
"""
Coleta de dados TransfereGov para Santa Catarina
APIs: PostgREST (transferenciasespeciais) + REST convencional (convenios)
"""

import requests
import json
import time
import os
from datetime import datetime

BASE_DIR = "/home/user/workspace/sc-inteligencia/raw/transferegov"
POSTGREST_BASE = "https://api.transferegov.gestao.gov.br/transferenciasespeciais"
REST_BASE = "https://api.transferegov.gestao.gov.br"

HEADERS_POSTGREST = {
    "Accept": "application/json",
}

SLEEP_BETWEEN = 0.5

def fetch_postgrest_paginated(url_base, params_base, label="endpoint"):
    """Pagina PostgREST incrementando offset de 1000 em 1000."""
    all_records = []
    offset = 0
    page = 0
    while True:
        params = dict(params_base)
        params["limit"] = 1000
        params["offset"] = offset
        print(f"  [{label}] Página {page+1} | offset={offset} ...")
        try:
            resp = requests.get(url_base, headers=HEADERS_POSTGREST, params=params, timeout=60)
            print(f"    Status: {resp.status_code}")
            if resp.status_code == 406:
                print("    [WARN] 406 - tentando sem header Accept ...")
                resp = requests.get(url_base, params=params, timeout=60)
                print(f"    Status (sem header): {resp.status_code}")
            if resp.status_code != 200:
                print(f"    [ERRO] Status {resp.status_code}: {resp.text[:300]}")
                break
            data = resp.json()
            if not data:
                print(f"    Lista vazia, paginação encerrada em offset={offset}.")
                break
            print(f"    Recebidos {len(data)} registros.")
            all_records.extend(data)
            if len(data) < 1000:
                print(f"    Menos de 1000 registros, última página.")
                break
            offset += 1000
            page += 1
        except Exception as e:
            print(f"    [EXCEPTION] {e}")
            break
        time.sleep(SLEEP_BETWEEN)
    return all_records


def fetch_rest_paginated(url_base, params_base, label="endpoint"):
    """Pagina REST convencional incrementando pagina."""
    all_records = []
    pagina = 1
    while True:
        params = dict(params_base)
        params["pagina"] = pagina
        print(f"  [{label}] Página {pagina} ...")
        try:
            resp = requests.get(url_base, headers={"Accept": "application/json"}, params=params, timeout=60)
            print(f"    Status: {resp.status_code}")
            if resp.status_code == 406:
                print("    [WARN] 406 - tentando sem header Accept ...")
                resp = requests.get(url_base, params=params, timeout=60)
                print(f"    Status (sem header): {resp.status_code}")
            if resp.status_code != 200:
                print(f"    [ERRO] Status {resp.status_code}: {resp.text[:300]}")
                break
            data = resp.json()
            # Tentar detectar lista de registros em diferentes estruturas
            records = None
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                # Tenta campos comuns
                for key in ["data", "content", "registros", "result", "items", "convenios"]:
                    if key in data and isinstance(data[key], list):
                        records = data[key]
                        break
                if records is None:
                    # Pode ser que o dict inteiro seja um registro ou estrutura diferente
                    # Tenta pegar qualquer lista
                    for v in data.values():
                        if isinstance(v, list):
                            records = v
                            break
                if records is None:
                    print(f"    [WARN] Estrutura inesperada: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    # Salva o raw para análise
                    all_records.append({"_raw_page": pagina, "_data": data})
                    break
            if not records:
                print(f"    Lista vazia, paginação encerrada na página {pagina}.")
                break
            print(f"    Recebidos {len(records)} registros.")
            all_records.extend(records)
            # Verificar se há mais páginas
            total_pages = None
            if isinstance(data, dict):
                for key in ["totalPaginas", "total_paginas", "lastPage", "totalPages", "paginas"]:
                    if key in data:
                        total_pages = data[key]
                        break
            if total_pages is not None:
                print(f"    Total de páginas: {total_pages}")
                if pagina >= total_pages:
                    break
            elif len(records) < params_base.get("tamanhoPagina", 100):
                print(f"    Menos registros que o tamanho da página, última página.")
                break
            pagina += 1
        except Exception as e:
            print(f"    [EXCEPTION] {e}")
            break
        time.sleep(SLEEP_BETWEEN)
    return all_records


def save_json(data, filepath, metadata=None):
    payload = {
        "metadata": metadata or {},
        "total_records": len(data) if isinstance(data, list) else "N/A",
        "collected_at": datetime.utcnow().isoformat() + "Z",
        "data": data
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  [SALVO] {filepath} ({payload['total_records']} registros)")


# =============================================================================
# TAREFA 1 — Planos de ação SC (PostgREST)
# =============================================================================
print("\n" + "="*60)
print("TAREFA 1: Planos de ação SC (PostgREST)")
print("="*60)

url_plano = f"{POSTGREST_BASE}/plano_acao_especial"
params_plano = {
    "uf_beneficiario_plano_acao": "eq.SC"
}

planos_sc = fetch_postgrest_paginated(url_plano, params_plano, label="plano_acao_SC")

save_json(
    planos_sc,
    os.path.join(BASE_DIR, "plano_acao_sc.json"),
    metadata={
        "source": "PostgREST /plano_acao_especial",
        "filter": "uf_beneficiario_plano_acao=eq.SC",
        "description": "Planos de ação para SC"
    }
)

# =============================================================================
# TAREFA 2 — Por deputados SC (PostgREST)
# =============================================================================
print("\n" + "="*60)
print("TAREFA 2: Planos de ação por deputados SC (PostgREST)")
print("="*60)

DEPUTADOS_SC = [
    "UCZAI",
    "TREVISAN",
    "CHIODINI",
    "REINEHR",
    "MARQUES",
    "ZANATTA",
    "PEZENTI",
    "ISMAEL",
    "TROVAO",
    "COBALCHINI",
    "LIMA",
    "FREITAS",
    "TOALDO",
    "CAROL",
]

all_dep_records = []
summary_dep = {}

for sobrenome in DEPUTADOS_SC:
    print(f"\n  Buscando deputado: {sobrenome}")
    params_dep = {
        "nome_parlamentar_emenda_plano_acao": f"ilike.*{sobrenome}*",
        "uf_beneficiario_plano_acao": "eq.SC"
    }
    records = fetch_postgrest_paginated(url_plano, params_dep, label=f"dep_{sobrenome}")
    # Tag com deputado para rastreabilidade
    for r in records:
        r["_query_sobrenome"] = sobrenome
    summary_dep[sobrenome] = len(records)
    all_dep_records.extend(records)
    print(f"  -> {sobrenome}: {len(records)} registros")
    time.sleep(SLEEP_BETWEEN)

save_json(
    all_dep_records,
    os.path.join(BASE_DIR, "plano_acao_por_dep_sc.json"),
    metadata={
        "source": "PostgREST /plano_acao_especial",
        "filter": "nome_parlamentar_emenda_plano_acao=ilike.*SOBRENOME* AND uf_beneficiario_plano_acao=eq.SC",
        "deputados_buscados": DEPUTADOS_SC,
        "summary_por_deputado": summary_dep
    }
)

# =============================================================================
# TAREFA 3 — Convênios SC (REST convencional)
# =============================================================================
print("\n" + "="*60)
print("TAREFA 3: Convênios SC (REST convencional)")
print("="*60)

url_convenios = f"{REST_BASE}/convenios/convenios"
params_convenios = {
    "uf": "SC",
    "tamanhoPagina": 100
}

convenios_sc = fetch_rest_paginated(url_convenios, params_convenios, label="convenios_SC")

save_json(
    convenios_sc,
    os.path.join(BASE_DIR, "convenios_sc.json"),
    metadata={
        "source": "REST /convenios/convenios",
        "filter": "uf=SC",
        "description": "Convênios para SC"
    }
)

# =============================================================================
# RESUMO FINAL
# =============================================================================
print("\n" + "="*60)
print("RESUMO FINAL")
print("="*60)
print(f"  Planos de ação SC:              {len(planos_sc):>8} registros")
print(f"  Planos por deputados SC:        {len(all_dep_records):>8} registros")
print(f"    Detalhamento por deputado:")
for nome, qtd in summary_dep.items():
    print(f"      {nome:<20}: {qtd:>6}")
print(f"  Convênios SC:                   {len(convenios_sc):>8} registros")
print("="*60)
print("Coleta concluída.")
