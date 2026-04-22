#!/usr/bin/env python3
"""
Complemento: Emendas dos senadores SC via materia/pesquisa
O endpoint /orcamento não existe na API do Senado (retorna 404).
Usamos o endpoint alternativo de matérias para capturar emendas legislativas.
"""

import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

BASE_SENADO = "https://legis.senado.leg.br/dadosabertos"
RAW_SENADO = Path("/home/user/workspace/sc-inteligencia/raw/senado")
SLEEP = 0.5


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_json(url, headers=None, params=None):
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json(), None
        else:
            return None, resp.status_code
    except Exception as e:
        return None, str(e)


# Carregar senadores SC já coletados
senadores_file = RAW_SENADO / "senadores_sc.json"
senadores_data = json.loads(senadores_file.read_text())
senadores_sc = senadores_data.get("dados", [])

print(f"Senadores SC carregados: {len(senadores_sc)}")
for s in senadores_sc:
    ident = s.get("IdentificacaoParlamentar", {})
    print(f"  {ident.get('NomeParlamentar')} (código: {ident.get('CodigoParlamentar')})")

HEADERS = {"Accept": "application/json"}

# ─────────────────────────────────────────────
# TAREFA 6 REVISADA — Emendas dos senadores SC
# Usar endpoint /materia/pesquisa/lista como alternativa ao /orcamento (404)
# ─────────────────────────────────────────────
print("\n=== TAREFA 6 (revisada): Emendas senadores SC via materia ===")
print("Nota: endpoint /senador/{codigo}/orcamento retorna 404 na API do Senado.")
print("Usando /materia/pesquisa/lista?codigoAutor={codigo}&siglaSubtipoMateria=EMC\n")

emendas_senadores = []

for sen in senadores_sc:
    ident = sen.get("IdentificacaoParlamentar", {})
    codigo = ident.get("CodigoParlamentar", "")
    nome_sen = ident.get("NomeParlamentar", str(codigo))

    # Tentativa 1: endpoint /orcamento (conforme especificado na tarefa)
    url_orc = f"{BASE_SENADO}/senador/{codigo}/orcamento"
    data_o, err_o = get_json(url_orc, headers=HEADERS)
    time.sleep(SLEEP)

    orcamento_status = {"erro": err_o, "url": url_orc} if err_o else data_o
    print(f"  {nome_sen}: /orcamento -> HTTP {err_o if err_o else 200}")

    # Alternativa: buscar emendas via matérias parlamentares por ano
    materias_por_ano = {}
    for ano in [2020, 2021, 2022, 2023, 2024]:
        url_mat = f"{BASE_SENADO}/materia/pesquisa/lista"
        params = {
            "codigoAutor": codigo,
            "siglaSubtipoMateria": "EMC",
            "ano": ano
        }
        data_m, err_m = get_json(url_mat, headers=HEADERS, params=params)
        time.sleep(SLEEP)

        if err_m:
            materias_por_ano[str(ano)] = {"erro": err_m, "url": url_mat}
        else:
            pb = data_m.get("PesquisaBasicaMateria", {})
            materias_raw = pb.get("Materias", {})
            mat_list = materias_raw.get("Materia", []) if isinstance(materias_raw, dict) else []
            # Filter strictly EMC
            emc_list = [m for m in mat_list if m.get("Sigla", "") == "EMC"]
            materias_por_ano[str(ano)] = emc_list
            print(f"    {ano}: {len(emc_list)} EMC encontradas")

    emendas_senadores.append({
        "codigo": codigo,
        "nome": nome_sen,
        "orcamento_endpoint": orcamento_status,
        "emendas_por_ano": materias_por_ano
    })

# Salvar resultado
obj = {
    "coletado_em": now_iso(),
    "fonte": f"{BASE_SENADO}/senador/{{codigo}}/orcamento (404) + {BASE_SENADO}/materia/pesquisa/lista?codigoAutor={{codigo}}&siglaSubtipoMateria=EMC",
    "nota": "O endpoint /senador/{codigo}/orcamento retorna 404. Dados alternativos coletados via /materia/pesquisa/lista.",
    "dados": emendas_senadores
}
out_path = RAW_SENADO / "emendas_senadores_sc.json"
out_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
size_kb = out_path.stat().st_size / 1024
print(f"\n  [SAVED] {out_path.name} ({size_kb:.1f} KB)")

# Resumo
print("\n=== RESUMO EMENDAS SENADORES SC ===")
for entry in emendas_senadores:
    total = sum(
        len(v) for v in entry["emendas_por_ano"].values()
        if isinstance(v, list)
    )
    print(f"  {entry['nome']}: {total} emendas EMC (2020-2024)")
