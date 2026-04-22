#!/usr/bin/env python3
"""
Coleta de dados FNS e FNDE para Santa Catarina
"""

import requests
import json
import time
from datetime import datetime

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; DataCollector/1.0)",
    "Accept": "application/json, text/html, */*",
})

def test_endpoint(url, params=None, label=""):
    """Testa um endpoint e retorna metadados + resposta"""
    print(f"\n[TEST] {label}")
    print(f"  URL: {url}")
    print(f"  Params: {params}")
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
        resp = SESSION.get(url, params=params, timeout=20)
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


def save_result(path, metadata):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[SAVED] {path}")


# ==============================================================================
# TAREFA 1 — FNS repasses por município SC
# ==============================================================================
print("\n" + "="*70)
print("TAREFA 1 — FNS repasses por município SC")
print("="*70)

resultados_tarefa1 = {
    "coletado_em": datetime.now().isoformat(),
    "tarefa": "FNS repasses SC",
    "endpoints_testados": [],
    "dados_coletados": [],
}

# Opção A — API v1 gestor/repasses com competencia
opcao_a = test_endpoint(
    "https://apifns.saude.gov.br/v1/gestor/repasses",
    params={"uf": "SC", "competencia": "202401"},
    label="Opção A - gestor/repasses competencia 202401"
)
resultados_tarefa1["endpoints_testados"].append(opcao_a)
time.sleep(0.5)

# Opção B — API v1 repasses com ano
opcao_b = test_endpoint(
    "https://apifns.saude.gov.br/v1/repasses",
    params={"uf": "SC", "ano": "2024"},
    label="Opção B - repasses ano 2024"
)
resultados_tarefa1["endpoints_testados"].append(opcao_b)
time.sleep(0.5)

# Opção C — Portal FNS web
opcao_c = test_endpoint(
    "https://www.fns.saude.gov.br/visao/consultarTransferenciaFundo.action",
    params={"uf": "SC"},
    label="Opção C - portal fns.saude.gov.br"
)
resultados_tarefa1["endpoints_testados"].append(opcao_c)
time.sleep(0.5)

# Tentar variações adicionais se as principais falharem
opcao_extra1 = test_endpoint(
    "https://apifns.saude.gov.br/v1/gestor/repasses",
    params={"uf": "SC", "competencia": "202301"},
    label="Opção A - gestor/repasses competencia 202301"
)
resultados_tarefa1["endpoints_testados"].append(opcao_extra1)
time.sleep(0.5)

# Se alguma opção retornou dados JSON, coletar múltiplas competências
competencias_2023 = [f"2023{str(m).zfill(2)}" for m in range(1, 13)]
competencias_2024 = [f"2024{str(m).zfill(2)}" for m in range(1, 4)]
todas_competencias = competencias_2023 + competencias_2024

# Determinar qual endpoint funciona
endpoint_funcional = None
for ep in resultados_tarefa1["endpoints_testados"]:
    if ep["json_disponivel"] and ep["status_http"] == 200:
        endpoint_funcional = ep
        break

if endpoint_funcional and "gestor/repasses" in endpoint_funcional["url"]:
    print(f"\n[INFO] Endpoint funcional encontrado: {endpoint_funcional['url']}")
    print("[INFO] Coletando todas as competências...")
    
    # Adicionar o que já coletamos
    if opcao_a["json_disponivel"]:
        resultados_tarefa1["dados_coletados"].append({
            "competencia": "202401",
            "dados": opcao_a["dados"]
        })
    
    for comp in todas_competencias:
        if comp == "202401":
            continue  # já coletado
        ep_result = test_endpoint(
            endpoint_funcional["url"],
            params={"uf": "SC", "competencia": comp},
            label=f"Coleta competencia {comp}"
        )
        if ep_result["json_disponivel"]:
            resultados_tarefa1["dados_coletados"].append({
                "competencia": comp,
                "dados": ep_result["dados"]
            })
        time.sleep(0.5)
elif endpoint_funcional and "/v1/repasses" in endpoint_funcional["url"] and "gestor" not in endpoint_funcional["url"]:
    print(f"\n[INFO] Usando endpoint B para múltiplos anos")
    for ano in ["2023", "2024"]:
        ep_result = test_endpoint(
            endpoint_funcional["url"],
            params={"uf": "SC", "ano": ano},
            label=f"Coleta ano {ano}"
        )
        if ep_result["json_disponivel"]:
            resultados_tarefa1["dados_coletados"].append({
                "ano": ano,
                "dados": ep_result["dados"]
            })
        time.sleep(0.5)
else:
    print("\n[INFO] Nenhum endpoint retornou JSON válido para TAREFA 1")

save_result("/home/user/workspace/sc-inteligencia/raw/fns/repasses_sc.json", resultados_tarefa1)


# ==============================================================================
# TAREFA 2 — FNS por número de emenda
# ==============================================================================
print("\n" + "="*70)
print("TAREFA 2 — FNS por número de emenda")
print("="*70)

resultados_tarefa2 = {
    "coletado_em": datetime.now().isoformat(),
    "tarefa": "FNS emenda",
    "endpoints_testados": [],
}

ep_emenda = test_endpoint(
    "https://apifns.saude.gov.br/v1/gestor/emenda",
    params={"numero": "202428550022"},
    label="Emenda 202428550022"
)
resultados_tarefa2["endpoints_testados"].append(ep_emenda)

if ep_emenda["json_disponivel"]:
    resultados_tarefa2["dados"] = ep_emenda["dados"]
else:
    resultados_tarefa2["dados"] = ep_emenda["dados"]

save_result("/home/user/workspace/sc-inteligencia/raw/fns/emenda_uczai_teste.json", resultados_tarefa2)


# ==============================================================================
# TAREFA 3 — FNDE PNAE SC
# ==============================================================================
print("\n" + "="*70)
print("TAREFA 3 — FNDE PNAE SC")
print("="*70)

resultados_tarefa3 = {
    "coletado_em": datetime.now().isoformat(),
    "tarefa": "FNDE PNAE SC",
    "endpoints_testados": [],
    "dados": None,
}

ep_pnae1 = test_endpoint(
    "https://www.fnde.gov.br/sigpcadm/api/v1/repasses",
    params={"programa": "PNAE", "uf": "SC", "ano": "2024"},
    label="PNAE via sigpcadm API"
)
resultados_tarefa3["endpoints_testados"].append(ep_pnae1)
time.sleep(0.5)

ep_pnae2 = test_endpoint(
    "https://dadosabertos.fnde.gov.br/api/3/action/datastore_search",
    params={"resource_id": "pnae-sc-2024"},
    label="PNAE via dadosabertos FNDE resource pnae-sc-2024"
)
resultados_tarefa3["endpoints_testados"].append(ep_pnae2)
time.sleep(0.5)

# Tentar CKAN datastore sem filtro de resource_id específico — buscar datasets PNAE
ep_pnae3 = test_endpoint(
    "https://dadosabertos.fnde.gov.br/api/3/action/package_search",
    params={"q": "PNAE SC", "rows": 5},
    label="CKAN package_search PNAE SC"
)
resultados_tarefa3["endpoints_testados"].append(ep_pnae3)
time.sleep(0.5)

# Também testar endpoint público FNDE
ep_pnae4 = test_endpoint(
    "https://dadosabertos.fnde.gov.br/api/3/action/package_list",
    label="CKAN package_list geral"
)
resultados_tarefa3["endpoints_testados"].append(ep_pnae4)
time.sleep(0.5)

# Determinar dados a salvar
for ep in resultados_tarefa3["endpoints_testados"]:
    if ep["json_disponivel"] and ep["status_http"] == 200:
        dados_raw = ep["dados"]
        # Verificar se é CKAN success
        if isinstance(dados_raw, dict) and dados_raw.get("success") == True:
            resultados_tarefa3["dados"] = dados_raw
            resultados_tarefa3["fonte_usada"] = ep["url"]
            break
        elif isinstance(dados_raw, list) or (isinstance(dados_raw, dict) and "status" not in dados_raw):
            resultados_tarefa3["dados"] = dados_raw
            resultados_tarefa3["fonte_usada"] = ep["url"]
            break

if resultados_tarefa3["dados"] is None:
    resultados_tarefa3["dados"] = {"status": "nenhum_endpoint_disponivel", "detalhes": "Todos endpoints testados sem dados válidos"}

save_result("/home/user/workspace/sc-inteligencia/raw/fnde/pnae_sc.json", resultados_tarefa3)


# ==============================================================================
# TAREFA 4 — FNDE PDDE SC
# ==============================================================================
print("\n" + "="*70)
print("TAREFA 4 — FNDE PDDE SC")
print("="*70)

resultados_tarefa4 = {
    "coletado_em": datetime.now().isoformat(),
    "tarefa": "FNDE PDDE SC",
    "endpoints_testados": [],
    "dados": None,
}

ep_pdde1 = test_endpoint(
    "https://dadosabertos.fnde.gov.br/api/3/action/datastore_search",
    params={"resource_id": "pdde"},
    label="PDDE via dadosabertos FNDE resource pdde"
)
resultados_tarefa4["endpoints_testados"].append(ep_pdde1)
time.sleep(0.5)

# Buscar dataset PDDE no CKAN
ep_pdde2 = test_endpoint(
    "https://dadosabertos.fnde.gov.br/api/3/action/package_search",
    params={"q": "PDDE", "rows": 5},
    label="CKAN package_search PDDE"
)
resultados_tarefa4["endpoints_testados"].append(ep_pdde2)
time.sleep(0.5)

# Se CKAN retornou datasets, tentar acessar o resource de PDDE
if ep_pdde2["json_disponivel"] and ep_pdde2["status_http"] == 200:
    dados_pdde2 = ep_pdde2["dados"]
    if isinstance(dados_pdde2, dict) and dados_pdde2.get("success"):
        results = dados_pdde2.get("result", {}).get("results", [])
        print(f"  Datasets PDDE encontrados: {len(results)}")
        for ds in results[:2]:
            print(f"    - {ds.get('name')} | {ds.get('title')}")
            for res in ds.get("resources", [])[:3]:
                print(f"      resource_id: {res.get('id')} | {res.get('name')}")
                # Tentar acessar esse resource com filtro SC
                ep_pdde_r = test_endpoint(
                    "https://dadosabertos.fnde.gov.br/api/3/action/datastore_search",
                    params={"resource_id": res.get("id"), "q": "SC", "limit": 100},
                    label=f"PDDE resource {res.get('id')} filtrado SC"
                )
                resultados_tarefa4["endpoints_testados"].append(ep_pdde_r)
                if ep_pdde_r["json_disponivel"] and ep_pdde_r["status_http"] == 200:
                    rd = ep_pdde_r["dados"]
                    if isinstance(rd, dict) and rd.get("success"):
                        registros = rd.get("result", {}).get("records", [])
                        if registros:
                            # filtrar SC
                            sc_registros = [r for r in registros if "SC" in str(r).upper()]
                            resultados_tarefa4["dados"] = {
                                "source_resource_id": res.get("id"),
                                "total_registros": len(registros),
                                "registros_sc": sc_registros,
                            }
                            break
                time.sleep(0.5)
            if resultados_tarefa4["dados"]:
                break

if resultados_tarefa4["dados"] is None:
    # Verificar se o primeiro endpoint retornou algo
    if ep_pdde1["json_disponivel"] and ep_pdde1["status_http"] == 200:
        resultados_tarefa4["dados"] = ep_pdde1["dados"]
    else:
        resultados_tarefa4["dados"] = {"status": "nenhum_endpoint_disponivel", "detalhes": "Todos endpoints testados sem dados válidos"}

save_result("/home/user/workspace/sc-inteligencia/raw/fnde/pdde_sc.json", resultados_tarefa4)

print("\n" + "="*70)
print("COLETA CONCLUÍDA")
print("="*70)
print("Arquivos salvos:")
print("  - /home/user/workspace/sc-inteligencia/raw/fns/repasses_sc.json")
print("  - /home/user/workspace/sc-inteligencia/raw/fns/emenda_uczai_teste.json")
print("  - /home/user/workspace/sc-inteligencia/raw/fnde/pnae_sc.json")
print("  - /home/user/workspace/sc-inteligencia/raw/fnde/pdde_sc.json")
