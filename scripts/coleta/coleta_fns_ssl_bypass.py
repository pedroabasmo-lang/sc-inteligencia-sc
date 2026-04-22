#!/usr/bin/env python3
"""
Coleta FNS com SSL verify=False e testes adicionais de endpoints
"""

import requests
import json
import time
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_endpoint(url, params=None, label="", verify=False, timeout=25):
    print(f"\n[TEST] {label}")
    print(f"  URL: {url}")
    result = {
        "label": label,
        "url": url,
        "params": params,
        "status_http": None,
        "content_type": None,
        "primeiros_500_chars": None,
        "json_disponivel": False,
        "dados": None,
        "erro": None,
    }
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        resp = requests.get(url, params=params, timeout=timeout, verify=verify, headers=headers, allow_redirects=True)
        result["status_http"] = resp.status_code
        result["content_type"] = resp.headers.get("Content-Type", "")
        preview = resp.text[:500]
        result["primeiros_500_chars"] = preview
        print(f"  Status: {resp.status_code}")
        print(f"  Content-Type: {result['content_type']}")
        print(f"  Preview: {preview[:300]}")

        ct = result["content_type"].lower()
        if "json" in ct:
            try:
                result["dados"] = resp.json()
                result["json_disponivel"] = True
            except Exception as e:
                result["erro"] = f"JSON parse error: {e}"
        elif resp.text.strip().startswith("{") or resp.text.strip().startswith("["):
            try:
                result["dados"] = resp.json()
                result["json_disponivel"] = True
            except Exception as e:
                result["erro"] = f"JSON parse error: {e}"
        else:
            result["dados"] = {"status": "html_retornado", "endpoint_nao_disponivel": True}
    except Exception as e:
        result["erro"] = str(e)
        result["dados"] = {"status": "erro_conexao", "detalhe": str(e)}
        print(f"  ERRO: {e}")
    time.sleep(0.5)
    return result


all_results = {"coletado_em": datetime.now().isoformat(), "testes": []}

# ==============================================================================
# FNS saude.gov.br — SSL bypass
# ==============================================================================
print("\n=== FNS com verify=False ===")

fns_endpoints = [
    ("https://www.fns.saude.gov.br/visao/consultarTransferenciaFundo.action", {"uf": "SC"}, "FNS web SSL bypass"),
    ("https://fns.saude.gov.br/visao/consultarTransferenciaFundo.action", {"uf": "SC"}, "FNS sem www SSL bypass"),
    # Tentar endpoint REST da API FNS com SSL bypass
    ("https://apifns.saude.gov.br/v1/gestor/repasses", {"uf": "SC", "competencia": "202401"}, "apiFNS SSL bypass"),
    # Tentar FNS2 ou API diferente
    ("https://apifns.saude.gov.br/v2/repasses", {"uf": "SC", "competencia": "202401"}, "apiFNS v2 SSL bypass"),
    # Endpoint de repasses do FNS sem version
    ("https://api.fns.saude.gov.br/repasses", {"uf": "SC"}, "api.fns.saude repasses"),
    ("https://api.saude.gov.br/fns/repasses", {"uf": "SC"}, "api.saude.gov.br/fns"),
    # Dados.saude
    ("https://dados.saude.gov.br/api/3/action/package_search", {"q": "repasse FNS"}, "dados.saude package_search"),
    # RNDS/CONASS API
    ("https://integracao.esus.ufsc.br/api/fns/repasses", {"uf": "SC"}, "esus.ufsc.br FNS"),
]

for url, params, label in fns_endpoints:
    r = test_endpoint(url, params=params, label=label, verify=False, timeout=15)
    all_results["testes"].append(r)

# ==============================================================================
# Portal da Transparência sem autenticação — endpoints que são públicos
# ==============================================================================
print("\n=== Portal da Transparência (endpoints sem auth) ===")

transparencia_public = [
    # Alguns endpoints do Portal Transparência são públicos
    ("https://api.portaldatransparencia.gov.br/api-de-dados/entes-federados-municipios-transferencias", {"codigoUF": "42", "ano": "2024", "pagina": "1"}, "Entes federados municípios SC"),
    ("https://api.portaldatransparencia.gov.br/api-de-dados/programas-sociais-beneficiarios", {"codigoUF": "42"}, "Programas sociais SC"),
]

for url, params, label in transparencia_public:
    r = test_endpoint(url, params=params, label=label, verify=True, timeout=20)
    all_results["testes"].append(r)

# ==============================================================================
# FNDE endpoints alternativos 
# ==============================================================================
print("\n=== FNDE endpoints alternativos ===")

fnde_alts = [
    # FNDE dados abertos CKAN alternativo
    ("https://www.fnde.gov.br/index.php/programas/alimentacao-escolar/area-para-gestores/dados-da-alimentacao-escolar", {}, "FNDE PNAE gestores"),
    # SIGEF liberações JSON  
    ("https://www.fnde.gov.br/sigefweb/index.php/liberacoes/consultarLiberacao", {"uf": "SC", "programa": "PNAE", "ano": "2024", "format": "json"}, "SIGEF liberação JSON SC"),
    # FNDE portal antigo
    ("https://www.fnde.gov.br/pnae/pnae-area-gestores/", {}, "FNDE PNAE portal"),
    # FNDE transferências via portal
    ("https://www.fnde.gov.br/siope/relatorioConsolidadoEstadualMunicipal.do", {"uf": "SC", "exercicio": "2024"}, "FNDE SIOPE consolidado SC"),
    # dadosabertos.fnde.gov.br resolução DNS alternativa
    ("http://dadosabertos.fnde.gov.br/api/3/action/package_list", {}, "FNDE dadosabertos HTTP"),
]

for url, params, label in fnde_alts:
    r = test_endpoint(url, params=params, label=label, verify=False, timeout=15)
    all_results["testes"].append(r)

with open("/home/user/workspace/sc-inteligencia/raw/ssl_bypass_tests.json", "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

print("\n[SAVED] /home/user/workspace/sc-inteligencia/raw/ssl_bypass_tests.json")

print("\n" + "="*60)
print("RESUMO")
print("="*60)
for t in all_results["testes"]:
    status = t["status_http"] or "ERRO"
    json_ok = "✓ JSON" if t["json_disponivel"] else "✗ sem JSON"
    print(f"  [{status}] {json_ok} | {t['label']}")
    if t["erro"]:
        print(f"         -> {t['erro'][:120]}")
