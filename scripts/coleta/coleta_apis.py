#!/usr/bin/env python3
"""Testa endpoints de Transparência SC, SEF-SC e DATASUS."""

import json
import requests
import os

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SC-Inteligencia/1.0; +https://github.com/sc-inteligencia)"
}
TIMEOUT = 30

def test_endpoint(url, description=""):
    """Testa um endpoint HTTP e retorna status + preview da resposta."""
    result = {"url": url, "description": description}
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        result["status_code"] = r.status_code
        result["content_type"] = r.headers.get("Content-Type", "")
        raw = r.text
        result["response_preview"] = raw[:500]
        result["response_length"] = len(raw)
        print(f"  [{r.status_code}] {url}")
        print(f"       Content-Type: {result['content_type']}")
        print(f"       Preview: {raw[:200]!r}")
    except Exception as e:
        result["status_code"] = None
        result["error"] = str(e)
        print(f"  [ERROR] {url} → {e}")
    return result

# ──────────────────────────────────────────────
# TAREFA 4 — Transparência SC
# ──────────────────────────────────────────────
print("\n=== TAREFA 4: Transparência SC ===")
transp_results = []
transp_urls = [
    ("https://www.transparencia.sc.gov.br/api/emendas?uf=SC&ano=2024", "Emendas SC 2024 (v1)"),
    ("https://transparencia.sc.gov.br/api/v1/emendas?ano=2024", "Emendas SC 2024 (v1 alt)"),
    ("https://www.transparencia.sc.gov.br/", "Portal principal Transparência SC"),
]
for url, desc in transp_urls:
    transp_results.append(test_endpoint(url, desc))

out4 = "/home/user/workspace/sc-inteligencia/raw/transparencia_sc/status_endpoints.json"
with open(out4, "w", encoding="utf-8") as f:
    json.dump(transp_results, f, ensure_ascii=False, indent=2)
print(f"[OK] Salvo em {out4}")

# ──────────────────────────────────────────────
# TAREFA 5 — SEF-SC / dados.sc.gov.br
# ──────────────────────────────────────────────
print("\n=== TAREFA 5: SEF-SC ===")
sef_results = []
sef_urls = [
    ("https://www.sef.sc.gov.br/dados-abertos/api/v1/receitas?ano=2024", "SEF-SC receitas 2024"),
    ("https://dados.sc.gov.br/api/3/action/package_list", "CKAN dados.sc.gov.br package list"),
    ("https://www.sef.sc.gov.br/", "Portal SEF-SC"),
    ("https://dados.sc.gov.br/", "Portal dados.sc.gov.br"),
]
for url, desc in sef_urls:
    sef_results.append(test_endpoint(url, desc))

out5 = "/home/user/workspace/sc-inteligencia/raw/sef_sc/status_endpoints.json"
with open(out5, "w", encoding="utf-8") as f:
    json.dump(sef_results, f, ensure_ascii=False, indent=2)
print(f"[OK] Salvo em {out5}")

# ──────────────────────────────────────────────
# TAREFA 6 — DATASUS repasses saúde
# ──────────────────────────────────────────────
print("\n=== TAREFA 6: DATASUS ===")
datasus_results = []
datasus_urls = [
    ("https://apidadosabertos.saude.gov.br/v1/financiamento/repasses?uf=SC&ano=2024", "DATASUS repasses SC 2024 (v1)"),
    ("https://apidatasus.datasus.gov.br/api/v1/repasses?uf=SC", "DATASUS repasses SC (alt)"),
    ("https://apidadosabertos.saude.gov.br/v1/", "DATASUS API raiz"),
]
for url, desc in datasus_urls:
    datasus_results.append(test_endpoint(url, desc))

out6 = "/home/user/workspace/sc-inteligencia/raw/datasus/status_endpoints.json"
with open(out6, "w", encoding="utf-8") as f:
    json.dump(datasus_results, f, ensure_ascii=False, indent=2)
print(f"[OK] Salvo em {out6}")

print("\n=== Coleta de APIs concluída ===")
