#!/usr/bin/env python3
"""
Coleta alternativa — testa variações de domínio e endpoints públicos FNS/FNDE
"""

import requests
import json
import time
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_endpoint(url, params=None, label="", verify=True):
    """Testa um endpoint e retorna metadados + resposta"""
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
        "verify_ssl": verify,
    }
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json, */*",
        }
        resp = requests.get(url, params=params, timeout=20, verify=verify, headers=headers)
        result["status_http"] = resp.status_code
        result["content_type"] = resp.headers.get("Content-Type", "")
        preview = resp.text[:500]
        result["primeiros_500_chars"] = preview
        print(f"  Status: {resp.status_code}")
        print(f"  Content-Type: {result['content_type']}")
        print(f"  Preview: {preview[:200]}")

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

# ==============================================================================
# Variações de domínio FNS (api sem www)
# ==============================================================================
print("\n[INFO] Testando variações de domínio FNS...")

fns_alternativas = [
    # API sem subdomínio api
    ("https://fns.saude.gov.br/visao/consultarTransferenciaFundo.action", {"uf": "SC"}, "FNS sem www", False),
    # Portal alternativo
    ("https://portaldatransparencia.gov.br/transferencias/consulta", {"uf": "SC", "orgao": "36201"}, "Portal Transparência FNS", True),
    # Dados abertos saúde
    ("https://dados.saude.gov.br/api/3/action/package_search", {"q": "FNS repasse SC"}, "Dados abertos saúde", True),
    # API saúde gov br
    ("https://apidadosnet.saude.gov.br/v1/repasses", {"uf": "SC"}, "apidadosnet saúde", True),
    # Portal FNS alternativo
    ("http://www.fns.saude.gov.br/visao/consultarTransferenciaFundo.action", {"uf": "SC"}, "FNS HTTP (sem SSL)", True),
]

resultados_alt = {"coletado_em": datetime.now().isoformat(), "testes": []}

for url, params, label, verify in fns_alternativas:
    r = test_endpoint(url, params=params, label=label, verify=verify)
    resultados_alt["testes"].append(r)
    time.sleep(0.5)

# ==============================================================================
# Testar Portal da Transparência — repasses fundo a fundo para SC
# ==============================================================================
print("\n[INFO] Testando Portal da Transparência Federal...")

# Portal da transparência tem API pública para transferências
transparencia_tests = [
    (
        "https://api.portaldatransparencia.gov.br/api-de-dados/transferencias-financeiras",
        {"codigoUF": "42", "ano": "2024", "pagina": "1"},
        "Portal Transparência transferências SC 2024"
    ),
    (
        "https://api.portaldatransparencia.gov.br/api-de-dados/transferencias-fundo-a-fundo",
        {"codigoUF": "42", "ano": "2024", "pagina": "1"},
        "Portal Transparência fundo-a-fundo SC 2024"
    ),
]

for url, params, label in transparencia_tests:
    r = test_endpoint(url, params=params, label=label, verify=True)
    resultados_alt["testes"].append(r)
    time.sleep(0.5)

# ==============================================================================
# FNDE dados abertos via CKAN alternativo
# ==============================================================================
print("\n[INFO] Testando FNDE via portal alternativo...")

fnde_tests = [
    (
        "https://www.fnde.gov.br/siope/consultaRepasseResumido.do",
        {"uf": "SC", "exercicio": "2024"},
        "FNDE SIOPE repasse SC 2024"
    ),
    (
        "https://www.fnde.gov.br/pls/simad/internet_fnde.liberacao_download_pkg.liberacaodownload",
        {"p_programa": "PNAE", "p_uf": "SC", "p_ano": "2024"},
        "FNDE SIMAD PNAE SC 2024"
    ),
    # FNDE SIGEF API
    (
        "https://www.fnde.gov.br/sigefweb/index.php/liberacoes",
        {"uf": "SC", "programa": "PNAE", "ano": "2024", "format": "json"},
        "FNDE SIGEF liberações PNAE SC"
    ),
]

for url, params, label in fnde_tests:
    r = test_endpoint(url, params=params, label=label, verify=True)
    resultados_alt["testes"].append(r)
    time.sleep(0.5)

# Salvar resultados alternativos
with open("/home/user/workspace/sc-inteligencia/raw/alternativas_testadas.json", "w", encoding="utf-8") as f:
    json.dump(resultados_alt, f, ensure_ascii=False, indent=2, default=str)

print("\n[SAVED] /home/user/workspace/sc-inteligencia/raw/alternativas_testadas.json")

# Resumo
print("\n" + "="*60)
print("RESUMO TESTES ALTERNATIVOS")
print("="*60)
for t in resultados_alt["testes"]:
    status = t["status_http"] or "ERRO"
    json_ok = "JSON OK" if t["json_disponivel"] else "sem JSON"
    print(f"  [{status}] {json_ok} | {t['label']}")
    if t["erro"]:
        print(f"         Erro: {t['erro'][:100]}")
