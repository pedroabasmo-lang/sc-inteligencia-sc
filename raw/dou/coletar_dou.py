#!/usr/bin/env python3
"""
Coleta portarias do DOU relacionadas a emendas parlamentares de SC.
"""
import json
import time
import datetime
import requests

OUTPUT_DIR = "/home/user/workspace/sc-inteligencia/raw/dou"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}

def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"

def fetch(url, params=None):
    """Fetch URL, return (status_code, content_type, text)."""
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        ct = resp.headers.get("Content-Type", "")
        return resp.status_code, ct, resp.text
    except Exception as e:
        return None, "error", str(e)

def parse_response(status, content_type, text, url):
    """Build a structured result dict."""
    result = {
        "coletado_em": now_iso(),
        "fonte": url,
        "status_http": status,
        "content_type": content_type,
    }

    if status is None:
        result["disponivel"] = False
        result["status"] = "error"
        result["dados"] = text
        return result

    is_json = "json" in content_type.lower()
    is_html = "html" in content_type.lower()

    if is_json:
        try:
            result["dados"] = json.loads(text)
            result["disponivel"] = True
            result["status"] = "json"
        except json.JSONDecodeError:
            result["disponivel"] = False
            result["status"] = "json_parse_error"
            result["dados"] = text[:2000]
    elif is_html:
        result["disponivel"] = False
        result["status"] = "html"
        result["endpoint"] = url
        # Save first 500 chars to help debug
        result["dados_preview"] = text[:500]
    else:
        # Try to parse as JSON anyway
        try:
            result["dados"] = json.loads(text)
            result["disponivel"] = True
            result["status"] = "json"
        except json.JSONDecodeError:
            result["disponivel"] = False
            result["status"] = "unknown"
            result["dados"] = text[:2000]

    return result

def save(filename, data):
    path = f"{OUTPUT_DIR}/{filename}"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  -> Salvo: {path}")

# ─────────────────────────────────────────────────────────────────────────────
# TAREFA 1a — Consulta pública DOU (emenda parlamentar SC 2024)
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 1a — DOU consulta pública (emenda parlamentar SC)")
url_1a = (
    "https://www.in.gov.br/consulta/-/buscar/dou"
    "?q=emenda+parlamentar+Santa+Catarina"
    "&s=todos"
    "&exactDate=personalizado"
    "&startDate=01-01-2024"
    "&endDate=31-12-2024"
)
status, ct, text = fetch(url_1a)
print(f"  Status HTTP: {status}  |  Content-Type: {ct}")
result_1a = parse_response(status, ct, text, url_1a)
save("busca_emenda_parlamentar_sc_2024.json", result_1a)
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# TAREFA 1a (variant) — Try with Accept: application/json explicitly
# ─────────────────────────────────────────────────────────────────────────────
print()
print("TAREFA 1a (variant) — DOU consulta pública com Accept: application/json")
headers_json = {**HEADERS, "Accept": "application/json"}
url_1a_v = (
    "https://www.in.gov.br/consulta/-/buscar/dou"
    "?q=emenda+parlamentar+Santa+Catarina"
    "&s=todos"
    "&exactDate=personalizado"
    "&startDate=01-01-2024"
    "&endDate=31-12-2024"
)
try:
    resp = requests.get(url_1a_v, headers=headers_json, timeout=30)
    ct_v = resp.headers.get("Content-Type", "")
    print(f"  Status HTTP: {resp.status_code}  |  Content-Type: {ct_v}")
    result_1a_v = parse_response(resp.status_code, ct_v, resp.text, url_1a_v)
    save("busca_emenda_parlamentar_sc_2024_json_accept.json", result_1a_v)
except Exception as e:
    print(f"  Erro: {e}")
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# TAREFA 1b — API estruturada DOU /servicos/buscar
# ─────────────────────────────────────────────────────────────────────────────
print()
print("TAREFA 1b — DOU API /servicos/buscar")
url_1b = "https://www.in.gov.br/servicos/buscar"
params_1b = {
    "q": "emenda parlamentar SC",
    "data_inicio": "2024-01-01",
    "data_fim": "2024-12-31",
    "tipoPesquisa": "todos",
}
status, ct, text = fetch(url_1b, params=params_1b)
print(f"  Status HTTP: {status}  |  Content-Type: {ct}")
result_1b = parse_response(status, ct, text, url_1b + "?" + "&".join(f"{k}={v}" for k,v in params_1b.items()))
save("busca_api_servicos_buscar.json", result_1b)
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# TAREFA 1b (variant) — Try known DOU search API endpoint
# ─────────────────────────────────────────────────────────────────────────────
print()
print("TAREFA 1b (variant) — DOU API /servicos/buscar?q=...")
url_1b_v2 = "https://www.in.gov.br/servicos/buscar?q=emenda+parlamentar+Santa+Catarina&data_inicio=2024-01-01&data_fim=2024-12-31&tipoPesquisa=todos"
status, ct, text = fetch(url_1b_v2)
print(f"  Status HTTP: {status}  |  Content-Type: {ct}")
result_1b_v2 = parse_response(status, ct, text, url_1b_v2)
save("busca_api_servicos_buscar_v2.json", result_1b_v2)
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# TAREFA 2 — dados.gov.br package_search
# ─────────────────────────────────────────────────────────────────────────────
print()
print("TAREFA 2 — dados.gov.br package_search")
url_2 = "https://dados.gov.br/api/3/action/package_search"
params_2 = {"q": "diario oficial emenda parlamentar"}
status, ct, text = fetch(url_2, params=params_2)
print(f"  Status HTTP: {status}  |  Content-Type: {ct}")
result_2 = parse_response(status, ct, text, url_2 + "?q=diario+oficial+emenda+parlamentar")
save("dados_gov_dou.json", result_2)
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# TAREFA 2b — dados.gov.br package_search for DOU dataset
# ─────────────────────────────────────────────────────────────────────────────
print()
print("TAREFA 2b — dados.gov.br package_search (diario oficial uniao)")
url_2b = "https://dados.gov.br/api/3/action/package_search"
params_2b = {"q": "diario oficial uniao portaria"}
status, ct, text = fetch(url_2b, params=params_2b)
print(f"  Status HTTP: {status}  |  Content-Type: {ct}")
result_2b = parse_response(status, ct, text, url_2b + "?q=diario+oficial+uniao+portaria")
save("dados_gov_dou_portaria.json", result_2b)
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# TAREFA 3 — Busca pela emenda do Uczai (número 202428550022)
# ─────────────────────────────────────────────────────────────────────────────
print()
print("TAREFA 3 — Busca emenda Uczai (202428550022)")
url_3 = "https://www.in.gov.br/consulta/-/buscar/dou?q=202428550022&s=todos"
status, ct, text = fetch(url_3)
print(f"  Status HTTP: {status}  |  Content-Type: {ct}")
result_3 = parse_response(status, ct, text, url_3)
save("busca_emenda_uczai.json", result_3)
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# TAREFA 3b — Try DOU Open Data API (Querido Diário style)
# ─────────────────────────────────────────────────────────────────────────────
print()
print("TAREFA 3b — DOU API alternativa (inlabs / open data)")
url_3b = "https://inlabs.in.gov.br/openaccess/portaria"
status, ct, text = fetch(url_3b)
print(f"  Status HTTP: {status}  |  Content-Type: {ct}")
result_3b = parse_response(status, ct, text, url_3b)
save("dou_inlabs_portaria.json", result_3b)
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# Extra — DOU Querido Diário (Open Knowledge Brasil)
# ─────────────────────────────────────────────────────────────────────────────
print()
print("EXTRA — Querido Diário API (OK Brasil)")
url_qd = "https://queridodiario.ok.org.br/api/gazettes"
params_qd = {
    "territory_id": "",
    "query": "emenda parlamentar Santa Catarina",
    "published_since": "2024-01-01",
    "published_until": "2024-12-31",
    "size": 10,
}
status, ct, text = fetch(url_qd, params=params_qd)
print(f"  Status HTTP: {status}  |  Content-Type: {ct}")
result_qd = parse_response(status, ct, text, url_qd)
save("querido_diario_emenda_sc.json", result_qd)
time.sleep(1)

# ─────────────────────────────────────────────────────────────────────────────
# RESUMO
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("RESUMO DOS ENDPOINTS")
print("=" * 60)
results = {
    "1a (consulta DOU SC 2024)": result_1a,
    "1a_v (consulta DOU SC 2024, JSON Accept)": result_1a_v,
    "1b (servicos/buscar)": result_1b,
    "1b_v2 (servicos/buscar v2)": result_1b_v2,
    "2 (dados.gov.br emenda parlamentar)": result_2,
    "2b (dados.gov.br portaria)": result_2b,
    "3 (busca Uczai 202428550022)": result_3,
    "3b (inlabs portaria)": result_3b,
    "QD (Querido Diário)": result_qd,
}
summary = {}
for name, r in results.items():
    s = r.get("status", "?")
    http = r.get("status_http", "?")
    disp = r.get("disponivel", False)
    flag = "✓ JSON disponível" if disp else f"✗ {s}"
    print(f"  [{http}] {name}: {flag}")
    summary[name] = {"status_http": http, "status": s, "disponivel": disp}

summary_data = {
    "coletado_em": now_iso(),
    "resumo": summary,
}
save("resumo_endpoints.json", summary_data)
print()
print("Coleta concluída.")
