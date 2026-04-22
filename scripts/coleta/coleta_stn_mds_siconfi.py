#!/usr/bin/env python3
"""
Coleta de dados STN (FPM), MDS (Bolsa Família) e SICONFI para Santa Catarina
"""

import requests
import json
import time
import os
from datetime import datetime

# Diretórios
RAW_DIR = "/home/user/workspace/sc-inteligencia/raw"
STN_DIR = os.path.join(RAW_DIR, "stn")
MDS_DIR = os.path.join(RAW_DIR, "mds")
SICONFI_DIR = os.path.join(RAW_DIR, "siconfi")

os.makedirs(STN_DIR, exist_ok=True)
os.makedirs(MDS_DIR, exist_ok=True)
os.makedirs(SICONFI_DIR, exist_ok=True)

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; SCIntelligencia/1.0)"
}

results_log = []

def fetch_endpoint(url, label, verify=True, timeout=60):
    """Faz requisição GET e retorna (status_code, data, is_json, error)"""
    print(f"\n[FETCH] {label}")
    print(f"  URL: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=verify)
        status = resp.status_code
        content_type = resp.headers.get("Content-Type", "")
        print(f"  Status: {status} | Content-Type: {content_type}")

        is_json = False
        data = None
        error = None

        if status == 200:
            text = resp.text.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    data = resp.json()
                    is_json = True
                    if isinstance(data, dict):
                        keys = list(data.keys())[:5]
                        print(f"  JSON keys: {keys}")
                        if "items" in data:
                            print(f"  Records (items): {len(data.get('items', []))}")
                        elif "data" in data:
                            print(f"  Records (data): {len(data.get('data', []))}")
                        elif "result" in data:
                            print(f"  Records (result): {data.get('result', {})}")
                    elif isinstance(data, list):
                        print(f"  JSON array length: {len(data)}")
                except Exception as e:
                    error = f"JSON parse error: {e}"
                    print(f"  ERROR parsing JSON: {e}")
            elif text.lower().startswith("<!doctype") or text.lower().startswith("<html"):
                error = "Retornou HTML (não disponível)"
                print(f"  AVISO: Retornou HTML")
                data = {"html_preview": text[:500]}
            else:
                # Could still be valid (e.g. empty JSON)
                if text == "" or text == "null":
                    error = f"Resposta vazia ou null"
                    print(f"  AVISO: Resposta vazia")
                else:
                    error = f"Conteúdo inesperado: {text[:200]}"
                    print(f"  AVISO: Conteúdo inesperado: {text[:200]}")
        else:
            error = f"HTTP {status}"
            try:
                data = resp.json()
                print(f"  Corpo erro: {str(data)[:200]}")
            except:
                data = {"raw": resp.text[:500]}
            print(f"  ERRO: HTTP {status}")

        return status, data, is_json, error

    except requests.exceptions.SSLError as e:
        print(f"  SSL Error: {e}")
        return None, None, False, f"SSL Error: {str(e)[:200]}"
    except requests.exceptions.Timeout:
        print(f"  TIMEOUT")
        return None, None, False, f"Timeout após {timeout}s"
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return None, None, False, str(e)[:300]


def log_result(tarefa, label, url, status, is_json, error, record_count=None):
    results_log.append({
        "tarefa": tarefa,
        "label": label,
        "url": url,
        "http_status": status,
        "is_json": is_json,
        "error": error,
        "record_count": record_count,
        "functional": (is_json and status == 200)
    })


def save_json(path, data, metadata=None):
    """Salva dados com metadados"""
    payload = {
        "_metadata": {
            "coletado_em": datetime.utcnow().isoformat() + "Z",
            **(metadata or {})
        },
        "data": data
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    size = os.path.getsize(path)
    print(f"  Salvo: {path} ({size:,} bytes)")


def get_record_count(data):
    if data is None:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        if "items" in data:
            return len(data["items"])
        if "data" in data and isinstance(data["data"], list):
            return len(data["data"])
        if "count" in data:
            return data["count"]
        if "total_count" in data:
            return data["total_count"]
    return None


# ============================================================
# TAREFA 1 — FPM SC
# ============================================================
print("\n" + "="*60)
print("TAREFA 1 — STN/FPM SC 2024")
print("="*60)

fpm_best = None
fpm_meta = {}
fpm_all_attempts = []

# Opção 1: por no_uf=SC
url_fpm_uf = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/fpm?an_exercicio=2024&no_uf=SC"
status, data, is_json, error = fetch_endpoint(url_fpm_uf, "FPM by no_uf=SC")
rc = get_record_count(data)
log_result("FPM", "FPM no_uf=SC", url_fpm_uf, status, is_json, error, rc)
fpm_all_attempts.append({"label": "no_uf=SC", "url": url_fpm_uf, "status": status, "is_json": is_json, "error": error, "records": rc})
if is_json and status == 200:
    fpm_best = data
    fpm_meta = {"endpoint": url_fpm_uf, "parametro": "no_uf=SC", "records": rc}
time.sleep(0.5)

# Opção 2: por co_uf=42
url_fpm_co = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/fpm?an_exercicio=2024&co_uf=42"
status2, data2, is_json2, error2 = fetch_endpoint(url_fpm_co, "FPM by co_uf=42")
rc2 = get_record_count(data2)
log_result("FPM", "FPM co_uf=42", url_fpm_co, status2, is_json2, error2, rc2)
fpm_all_attempts.append({"label": "co_uf=42", "url": url_fpm_co, "status": status2, "is_json": is_json2, "error": error2, "records": rc2})
if is_json2 and status2 == 200 and fpm_best is None:
    fpm_best = data2
    fpm_meta = {"endpoint": url_fpm_co, "parametro": "co_uf=42", "records": rc2}
time.sleep(0.5)

# Salvar
save_json(
    os.path.join(STN_DIR, "fpm_sc_2024.json"),
    fpm_best,
    {
        **fpm_meta,
        "an_exercicio": 2024,
        "uf": "SC",
        "co_uf": 42,
        "endpoints_testados": fpm_all_attempts,
        "erro": None if fpm_best else "Nenhum endpoint retornou dados válidos"
    }
)


# ============================================================
# TAREFA 2 — CIDE SC
# ============================================================
print("\n" + "="*60)
print("TAREFA 2 — STN/CIDE SC 2024")
print("="*60)

url_cide = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/cide?an_exercicio=2024&co_uf=42"
status, data, is_json, error = fetch_endpoint(url_cide, "CIDE co_uf=42 2024")
rc = get_record_count(data)
log_result("CIDE", "CIDE co_uf=42 2024", url_cide, status, is_json, error, rc)
time.sleep(0.5)

save_json(
    os.path.join(STN_DIR, "cide_sc_2024.json"),
    data,
    {
        "endpoint": url_cide,
        "an_exercicio": 2024,
        "uf": "SC",
        "co_uf": 42,
        "records": rc,
        "erro": error if not is_json else None
    }
)


# ============================================================
# TAREFA 3 — MDS Bolsa Família SC
# ============================================================
print("\n" + "="*60)
print("TAREFA 3 — MDS Bolsa Família SC")
print("="*60)

mds_results = {}

# Opção 1: misocial
url_mds1 = "https://aplicacoes.mds.gov.br/sagi/servicos/misocial?q_tipoinfo=bf_munic&co_uf=42&q_periodo=202401"
s1, d1, j1, e1 = fetch_endpoint(url_mds1, "MDS misocial bf_munic co_uf=42")
rc1 = get_record_count(d1)
log_result("MDS_BF", "MDS misocial", url_mds1, s1, j1, e1, rc1)
mds_results["misocial"] = {"url": url_mds1, "status": s1, "is_json": j1, "error": e1, "records": rc1, "data_sample": str(d1)[:500] if d1 else None}
time.sleep(0.5)

# Opção 2: api.mds.gov.br cadunico
url_mds2 = "https://api.mds.gov.br/api/v1/cadunico?uf=SC&competencia=202401"
s2, d2, j2, e2 = fetch_endpoint(url_mds2, "MDS api.mds cadunico SC")
rc2 = get_record_count(d2)
log_result("MDS_BF", "MDS api.mds cadunico", url_mds2, s2, j2, e2, rc2)
mds_results["api_mds_cadunico"] = {"url": url_mds2, "status": s2, "is_json": j2, "error": e2, "records": rc2, "data_sample": str(d2)[:500] if d2 else None}
time.sleep(0.5)

# Opção 3: dados.gov.br CKAN
url_mds3 = "https://dados.gov.br/api/3/action/datastore_search?resource_id=bolsa-familia-sc"
s3, d3, j3, e3 = fetch_endpoint(url_mds3, "dados.gov.br CKAN bolsa-familia-sc")
rc3 = get_record_count(d3)
log_result("MDS_BF", "dados.gov.br CKAN", url_mds3, s3, j3, e3, rc3)
mds_results["dados_gov_br_ckan"] = {"url": url_mds3, "status": s3, "is_json": j3, "error": e3, "records": rc3, "data_sample": str(d3)[:500] if d3 else None}
time.sleep(0.5)

# Opção 4: Portal da Transparência - Bolsa Família por estado
url_mds4 = "https://api.portaldatransparencia.gov.br/api-de-dados/bolsa-familia-disponivel-por-municipio?anoMes=202401&codigoIbge=42"
s4, d4, j4, e4 = fetch_endpoint(url_mds4, "Portal Transparência BF estado SC 202401")
rc4 = get_record_count(d4)
log_result("MDS_BF", "Portal Transparencia BF", url_mds4, s4, j4, e4, rc4)
mds_results["portal_transparencia"] = {"url": url_mds4, "status": s4, "is_json": j4, "error": e4, "records": rc4, "data_sample": str(d4)[:500] if d4 else None}
time.sleep(0.5)

# Opção 5: VIS Data MDS
url_mds5 = "https://aplicacoes.mds.gov.br/vis/data3/v.php?q=bolsa_familia_beneficiarios_uf&competencia=202401&uf=42&tipo=json"
s5, d5, j5, e5 = fetch_endpoint(url_mds5, "MDS VIS Data BF beneficiários SC")
rc5 = get_record_count(d5)
log_result("MDS_BF", "MDS VIS Data", url_mds5, s5, j5, e5, rc5)
mds_results["mds_vis_data"] = {"url": url_mds5, "status": s5, "is_json": j5, "error": e5, "records": rc5, "data_sample": str(d5)[:500] if d5 else None}
time.sleep(0.5)

# Determinar melhor fonte
best_mds_key = None
for key, v in mds_results.items():
    if v["is_json"] and v["status"] == 200:
        best_mds_key = key
        break

# Para salvar dados reais, pegar o objeto completo do melhor endpoint
best_mds_data = None
if best_mds_key == "misocial":
    best_mds_data = d1
elif best_mds_key == "api_mds_cadunico":
    best_mds_data = d2
elif best_mds_key == "dados_gov_br_ckan":
    best_mds_data = d3
elif best_mds_key == "portal_transparencia":
    best_mds_data = d4
elif best_mds_key == "mds_vis_data":
    best_mds_data = d5

save_json(
    os.path.join(MDS_DIR, "bolsa_familia_sc.json"),
    {
        "melhor_fonte": best_mds_key,
        "melhor_data": best_mds_data,
        "todos_endpoints": mds_results
    },
    {
        "descricao": "Resultados de todos endpoints MDS testados para Bolsa Família SC",
        "periodo": "202401",
        "endpoints_testados": list(mds_results.keys()),
        "melhor_fonte": best_mds_key
    }
)


# ============================================================
# TAREFA 4 — SICONFI RGF e DCA SC
# ============================================================
print("\n" + "="*60)
print("TAREFA 4 — SICONFI RGF e DCA SC")
print("="*60)

# RGF
url_rgf = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rgf?an_exercicio=2024&co_uf=42&no_periodo=bimestre_1"
s_rgf, d_rgf, j_rgf, e_rgf = fetch_endpoint(url_rgf, "SICONFI RGF bimestre_1 2024 SC")
rc_rgf = get_record_count(d_rgf)
log_result("SICONFI_RGF", "RGF bimestre_1 2024", url_rgf, s_rgf, j_rgf, e_rgf, rc_rgf)
time.sleep(0.5)

save_json(
    os.path.join(SICONFI_DIR, "rgf_sc_2024.json"),
    d_rgf,
    {
        "endpoint": url_rgf,
        "an_exercicio": 2024,
        "co_uf": 42,
        "no_periodo": "bimestre_1",
        "records": rc_rgf,
        "erro": e_rgf if not j_rgf else None
    }
)

# DCA
url_dca = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca?an_exercicio=2023&co_uf=42"
s_dca, d_dca, j_dca, e_dca = fetch_endpoint(url_dca, "SICONFI DCA 2023 SC")
rc_dca = get_record_count(d_dca)
log_result("SICONFI_DCA", "DCA 2023", url_dca, s_dca, j_dca, e_dca, rc_dca)
time.sleep(0.5)

save_json(
    os.path.join(SICONFI_DIR, "dca_sc_2023.json"),
    d_dca,
    {
        "endpoint": url_dca,
        "an_exercicio": 2023,
        "co_uf": 42,
        "records": rc_dca,
        "erro": e_dca if not j_dca else None
    }
)


# ============================================================
# RESUMO FINAL
# ============================================================
print("\n" + "="*60)
print("RESUMO FINAL — STN + MDS + SICONFI SC")
print("="*60)

functional = [r for r in results_log if r["functional"]]
non_functional = [r for r in results_log if not r["functional"]]

print(f"\nEndpoints FUNCIONAIS ({len(functional)}):")
for r in functional:
    rec = f" | {r['record_count']} registros" if r['record_count'] is not None else ""
    print(f"  [OK]   [{r['tarefa']}] {r['label']}{rec}")
    print(f"         {r['url']}")

print(f"\nEndpoints NÃO FUNCIONAIS ({len(non_functional)}):")
for r in non_functional:
    print(f"  [FAIL] [{r['tarefa']}] {r['label']} | HTTP {r['http_status']} | {r['error']}")
    print(f"         {r['url']}")

# Salvar log
summary = {
    "_metadata": {
        "coletado_em": datetime.utcnow().isoformat() + "Z",
        "total_endpoints": len(results_log),
        "funcionais": len(functional),
        "nao_funcionais": len(non_functional)
    },
    "endpoints_funcionais": functional,
    "endpoints_nao_funcionais": non_functional,
    "log_completo": results_log
}

log_path = os.path.join(RAW_DIR, "coleta_stn_mds_siconfi_log.json")
with open(log_path, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f"\nLog salvo: {log_path}")

print("\nArquivos gerados:")
for root, dirs, files in os.walk(RAW_DIR):
    for fname in sorted(files):
        fpath = os.path.join(root, fname)
        size = os.path.getsize(fpath)
        print(f"  {fpath} ({size:,} bytes)")
