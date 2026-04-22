"""
Coleta de dados IBGE + BrasilAPI para os 295 municípios de Santa Catarina (UF=42)
v3 — formato correto de localidades para IBGE v3: N6[in N3[42]]
"""

import json
import time
import requests
from datetime import datetime, timezone

BASE_IBGE_V1 = "https://servicodados.ibge.gov.br/api/v1"
BASE_IBGE_V3 = "https://servicodados.ibge.gov.br/api/v3"
BASE_BRASIL_API = "https://brasilapi.com.br/api"
BASE_SICONFI = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"

HEADERS = {
    "User-Agent": "sc-inteligencia-coleta/3.0 (pesquisa)",
    "Accept": "application/json",
}

SLEEP_BETWEEN = 0.35

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_json(url, label=""):
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        msg = str(e)
        print(f"  [ERRO] {label or url[:80]}: {msg[:150]}")
        return None, msg

# ─────────────────────────────────────────────────────────────
# TAREFA 1 — Municípios SC (IBGE Localidades v1)
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 1: Municípios SC (IBGE Localidades)")
url_municipios = f"{BASE_IBGE_V1}/localidades/estados/42/municipios"
dados, erro = get_json(url_municipios, "municipios_sc")

if dados:
    out = {
        "coletado_em": now_iso(),
        "fonte": url_municipios,
        "dados": dados
    }
    with open("/home/user/workspace/sc-inteligencia/raw/ibge/municipios_sc.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"  OK: {len(dados)} municípios salvos em municipios_sc.json")
    municipios = dados
else:
    print(f"  FALHA: {erro}")
    municipios = []

time.sleep(SLEEP_BETWEEN)

# ─────────────────────────────────────────────────────────────
# TAREFA 2 — População 2022 (Censo 2022, tabela 9514, variável 93)
# Formato correto: N6[in N3[42]] para todos os municípios de SC
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 2: População 2022 (Censo 2022, tabela 9514/var 93)")

url_pop = (
    f"{BASE_IBGE_V3}/agregados/9514/periodos/2022/variaveis/93"
    f"?localidades=N6[in N3[42]]"
)
print(f"  Buscando todos os municípios SC em uma requisição...")
dados_pop, erro_pop = get_json(url_pop, "populacao_sc")

if dados_pop:
    # Contar municípios com dados
    total_mun_pop = sum(
        len(res.get("series", []))
        for var_obj in dados_pop
        for res in var_obj.get("resultados", [])
    )
    out_pop = {
        "coletado_em": now_iso(),
        "fonte": url_pop,
        "tabela": "9514",
        "variavel": "93 (População residente - Censo 2022)",
        "municipios_retornados": total_mun_pop,
        "dados": dados_pop
    }
    with open("/home/user/workspace/sc-inteligencia/raw/ibge/populacao_sc.json", "w", encoding="utf-8") as f:
        json.dump(out_pop, f, ensure_ascii=False, indent=2)
    print(f"  OK: {total_mun_pop} municípios com dados de população salvos")
else:
    # Fallback: coletar município por município
    print(f"  Falhou requisição única: {erro_pop}")
    print(f"  Fallback: coletando município por município...")
    resultados_pop = []
    erros_pop = []
    codigos = [str(m["id"]) for m in municipios]

    for i, cod in enumerate(codigos):
        url_single = (
            f"{BASE_IBGE_V3}/agregados/9514/periodos/2022/variaveis/93"
            f"?localidades=N6[{cod}]"
        )
        dados_single, erro_single = get_json(url_single, f"pop_{cod}")
        if dados_single:
            # Extrair valor
            val = None
            for var_obj in dados_single:
                for res in var_obj.get("resultados", []):
                    for serie in res.get("series", []):
                        for periodo, v in serie.get("serie", {}).items():
                            val = v
            nome = next((m["nome"] for m in municipios if str(m["id"]) == cod), cod)
            resultados_pop.append({
                "cod_ibge": cod,
                "nome": nome,
                "populacao_2022": val,
                "dados_brutos": dados_single
            })
        else:
            erros_pop.append({"cod_ibge": cod, "erro": erro_single})
        if (i + 1) % 50 == 0:
            print(f"    {i+1}/{len(codigos)} municípios processados...")
        time.sleep(SLEEP_BETWEEN)

    out_pop = {
        "coletado_em": now_iso(),
        "fonte": f"{BASE_IBGE_V3}/agregados/9514/periodos/2022/variaveis/93",
        "tabela": "9514",
        "variavel": "93 (População residente - Censo 2022)",
        "modo": "individual",
        "municipios_coletados": len(resultados_pop),
        "erros": erros_pop,
        "dados": resultados_pop
    }
    with open("/home/user/workspace/sc-inteligencia/raw/ibge/populacao_sc.json", "w", encoding="utf-8") as f:
        json.dump(out_pop, f, ensure_ascii=False, indent=2)
    print(f"  OK: {len(resultados_pop)} municípios, {len(erros_pop)} erros")

time.sleep(SLEEP_BETWEEN)

# ─────────────────────────────────────────────────────────────
# TAREFA 3 — PIB Municipal 2021 (tabela 5938, variável 37)
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 3: PIB Municipal 2021 (tabela 5938, variável 37)")

url_pib = (
    f"{BASE_IBGE_V3}/agregados/5938/periodos/2021/variaveis/37"
    f"?localidades=N6[in N3[42]]"
)
print(f"  Buscando todos os municípios SC em uma requisição...")
dados_pib, erro_pib = get_json(url_pib, "pib_sc")

if dados_pib:
    total_mun_pib = sum(
        len(res.get("series", []))
        for var_obj in dados_pib
        for res in var_obj.get("resultados", [])
    )
    out_pib = {
        "coletado_em": now_iso(),
        "fonte": url_pib,
        "tabela": "5938",
        "variavel": "37 (PIB a preços correntes - Mil Reais)",
        "municipios_retornados": total_mun_pib,
        "dados": dados_pib
    }
    with open("/home/user/workspace/sc-inteligencia/raw/ibge/pib_sc.json", "w", encoding="utf-8") as f:
        json.dump(out_pib, f, ensure_ascii=False, indent=2)
    print(f"  OK: {total_mun_pib} municípios com dados de PIB salvos")
else:
    # Fallback individual
    print(f"  Falhou requisição única: {erro_pib}")
    print(f"  Fallback: coletando município por município...")
    resultados_pib = []
    erros_pib = []
    codigos = [str(m["id"]) for m in municipios]

    for i, cod in enumerate(codigos):
        url_single = (
            f"{BASE_IBGE_V3}/agregados/5938/periodos/2021/variaveis/37"
            f"?localidades=N6[{cod}]"
        )
        dados_single, erro_single = get_json(url_single, f"pib_{cod}")
        if dados_single:
            val = None
            for var_obj in dados_single:
                for res in var_obj.get("resultados", []):
                    for serie in res.get("series", []):
                        for periodo, v in serie.get("serie", {}).items():
                            val = v
            nome = next((m["nome"] for m in municipios if str(m["id"]) == cod), cod)
            resultados_pib.append({
                "cod_ibge": cod,
                "nome": nome,
                "pib_2021_mil_reais": val,
                "dados_brutos": dados_single
            })
        else:
            erros_pib.append({"cod_ibge": cod, "erro": erro_single})
        if (i + 1) % 50 == 0:
            print(f"    {i+1}/{len(codigos)} municípios processados...")
        time.sleep(SLEEP_BETWEEN)

    out_pib = {
        "coletado_em": now_iso(),
        "fonte": f"{BASE_IBGE_V3}/agregados/5938/periodos/2021/variaveis/37",
        "tabela": "5938",
        "variavel": "37 (PIB a preços correntes - Mil Reais)",
        "modo": "individual",
        "municipios_coletados": len(resultados_pib),
        "erros": erros_pib,
        "dados": resultados_pib
    }
    with open("/home/user/workspace/sc-inteligencia/raw/ibge/pib_sc.json", "w", encoding="utf-8") as f:
        json.dump(out_pib, f, ensure_ascii=False, indent=2)
    print(f"  OK: {len(resultados_pib)} municípios, {len(erros_pib)} erros")

time.sleep(SLEEP_BETWEEN)

# ─────────────────────────────────────────────────────────────
# TAREFA 4 — BrasilAPI CNPJ Prefeituras SC
# CNPJs via SICONFI + dados cadastrais via BrasilAPI
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 4: CNPJs Prefeituras SC (SICONFI + BrasilAPI)")

# 4a: CNPJs via SICONFI
print("  4a: Obtendo CNPJs via SICONFI (Tesouro Nacional)...")
url_siconfi = f"{BASE_SICONFI}/entes"
dados_siconfi_raw, erro_siconfi = get_json(url_siconfi, "siconfi_entes")

cnpj_por_ibge = {}
if dados_siconfi_raw:
    items = dados_siconfi_raw.get("items", [])
    sc_items = [x for x in items if str(x.get("uf", "")) == "SC"]
    print(f"  4a: {len(sc_items)} municípios SC no SICONFI")
    for item in sc_items:
        cod = str(item.get("cod_ibge", ""))
        cnpj = str(item.get("cnpj", "")).strip()
        if cnpj:
            cnpj_por_ibge[cod] = cnpj

    out_siconfi_map = {
        "coletado_em": now_iso(),
        "fonte": url_siconfi,
        "nota": "SICONFI (STN) — CNPJs e dados fiscais das prefeituras SC",
        "dados": sc_items
    }
    with open("/home/user/workspace/sc-inteligencia/raw/brasilapi/siconfi_entes_sc.json", "w", encoding="utf-8") as f:
        json.dump(out_siconfi_map, f, ensure_ascii=False, indent=2)
    print(f"  4a: {len(cnpj_por_ibge)} CNPJs mapeados. Salvo siconfi_entes_sc.json")
else:
    print(f"  4a: FALHA SICONFI: {erro_siconfi}")

time.sleep(SLEEP_BETWEEN)

# 4b: Dados cadastrais via BrasilAPI
print(f"  4b: Buscando dados CNPJ na BrasilAPI para {len(cnpj_por_ibge)} municípios...")
resultados_cnpj = []
erros_cnpj = []
municipios_sem_cnpj = []

for i, mun in enumerate(municipios):
    cod = str(mun["id"])
    nome = mun["nome"]
    cnpj = cnpj_por_ibge.get(cod)

    if not cnpj:
        municipios_sem_cnpj.append({
            "cod_ibge": cod,
            "nome_municipio": nome,
            "cnpj": None,
            "motivo": "CNPJ não encontrado no SICONFI"
        })
        continue

    url_cnpj = f"{BASE_BRASIL_API}/cnpj/v1/{cnpj}"
    dados_cnpj, erro = get_json(url_cnpj, f"cnpj_{nome}")
    if dados_cnpj:
        resultados_cnpj.append({
            "cod_ibge": cod,
            "nome_municipio": nome,
            "cnpj": cnpj,
            "dados_cnpj": dados_cnpj
        })
    else:
        erros_cnpj.append({
            "cod_ibge": cod,
            "nome_municipio": nome,
            "cnpj": cnpj,
            "erro": erro
        })

    if (i + 1) % 50 == 0:
        print(f"    {i+1}/{len(municipios)} municípios processados (ok={len(resultados_cnpj)}, err={len(erros_cnpj)})...")
    time.sleep(SLEEP_BETWEEN)

print(f"  4b: Coletados={len(resultados_cnpj)}, erros={len(erros_cnpj)}, sem CNPJ={len(municipios_sem_cnpj)}")

out_cnpj = {
    "coletado_em": now_iso(),
    "fonte_cnpj": f"{BASE_BRASIL_API}/cnpj/v1/{{cnpj}}",
    "fonte_mapa_cnpj": url_siconfi,
    "nota": "CNPJs obtidos do SICONFI (STN). Dados cadastrais via BrasilAPI.",
    "total_municipios": len(municipios),
    "cnpjs_consultados": len(resultados_cnpj) + len(erros_cnpj),
    "cnpjs_coletados": len(resultados_cnpj),
    "erros": erros_cnpj,
    "dados": resultados_cnpj + municipios_sem_cnpj
}
with open("/home/user/workspace/sc-inteligencia/raw/brasilapi/cnpj_prefeituras_sc.json", "w", encoding="utf-8") as f:
    json.dump(out_cnpj, f, ensure_ascii=False, indent=2)
print(f"  Salvo cnpj_prefeituras_sc.json")

# ─────────────────────────────────────────────────────────────
# RESUMO FINAL
# ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("RESUMO FINAL")
print("=" * 60)

import os

arquivos = [
    ("/home/user/workspace/sc-inteligencia/raw/ibge/municipios_sc.json", "municipios"),
    ("/home/user/workspace/sc-inteligencia/raw/ibge/populacao_sc.json", "populacao"),
    ("/home/user/workspace/sc-inteligencia/raw/ibge/pib_sc.json", "pib"),
    ("/home/user/workspace/sc-inteligencia/raw/brasilapi/cnpj_prefeituras_sc.json", "cnpj"),
    ("/home/user/workspace/sc-inteligencia/raw/brasilapi/siconfi_entes_sc.json", "siconfi"),
]

for arq, tipo in arquivos:
    if not os.path.exists(arq):
        print(f"  {os.path.basename(arq)}: NÃO ENCONTRADO")
        continue
    size = os.path.getsize(arq)
    with open(arq, encoding="utf-8") as f:
        conteudo = json.load(f)
    nome = os.path.basename(arq)

    if tipo == "municipios":
        n = len(conteudo.get("dados", []))
        print(f"  {nome}: {n} municípios | {size/1024:.1f} KB")
    elif tipo == "populacao":
        if "municipios_retornados" in conteudo:
            n = conteudo["municipios_retornados"]
            print(f"  {nome}: {n} municípios com população | {size/1024:.1f} KB")
        else:
            n = conteudo.get("municipios_coletados", 0)
            erros = len(conteudo.get("erros", []))
            print(f"  {nome}: {n} municípios com população, {erros} erros | {size/1024:.1f} KB")
    elif tipo == "pib":
        if "municipios_retornados" in conteudo:
            n = conteudo["municipios_retornados"]
            print(f"  {nome}: {n} municípios com PIB | {size/1024:.1f} KB")
        else:
            n = conteudo.get("municipios_coletados", 0)
            erros = len(conteudo.get("erros", []))
            print(f"  {nome}: {n} municípios com PIB, {erros} erros | {size/1024:.1f} KB")
    elif tipo == "cnpj":
        coletados = conteudo.get("cnpjs_coletados", 0)
        total = conteudo.get("total_municipios", 0)
        erros = len(conteudo.get("erros", []))
        print(f"  {nome}: {coletados}/{total} CNPJs coletados, {erros} erros | {size/1024:.1f} KB")
    elif tipo == "siconfi":
        n = len(conteudo.get("dados", []))
        print(f"  {nome}: {n} municípios SC | {size/1024:.1f} KB")

print("=" * 60)
print("Coleta concluída!")
