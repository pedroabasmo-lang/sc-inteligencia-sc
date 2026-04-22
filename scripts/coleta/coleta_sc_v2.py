"""
Coleta de dados IBGE + BrasilAPI para os 295 municípios de Santa Catarina (UF=42)
v2 — corrigido com endpoints validados
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
    "User-Agent": "sc-inteligencia-coleta/2.0 (pesquisa)",
    "Accept": "application/json",
}

SLEEP_BETWEEN = 0.35  # segundos entre requisições

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_json(url, label="", extra_headers=None):
    h = {**HEADERS, **(extra_headers or {})}
    try:
        r = requests.get(url, headers=h, timeout=30)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        msg = str(e)
        print(f"  [ERRO] {label or url[:80]}: {msg[:120]}")
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
    print(f"  Salvos {len(dados)} municípios em municipios_sc.json")
    municipios = dados
else:
    print(f"  FALHA: {erro}")
    municipios = []

time.sleep(SLEEP_BETWEEN)

codigos = [str(m["id"]) for m in municipios]

# ─────────────────────────────────────────────────────────────
# TAREFA 2 — População 2022 (Censo 2022, tabela 9514, variável 93)
# Nota: tabela 6579/var 9324 retorna vazia; tabela 9514/var 93 é o Censo 2022
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 2: População 2022 (Censo 2022, tabela 9514, variável 93)")
print("  Nota: tabela 6579/var 9324 retorna vazia; usando tabela 9514/var 93")

LOTE = 50
resultados_pop = []
erros_pop = []

for i in range(0, len(codigos), LOTE):
    lote = codigos[i:i+LOTE]
    cods_pipe = "|".join(lote)
    url_pop = (
        f"{BASE_IBGE_V3}/agregados/9514/periodos/2022/variaveis/93"
        f"?localidades=N6[{cods_pipe}]"
    )
    print(f"  Lote {i//LOTE + 1}/{(len(codigos)-1)//LOTE + 1}: municípios {i+1}–{i+len(lote)}")
    dados_lote, erro = get_json(url_pop, f"populacao_lote_{i//LOTE+1}")
    if dados_lote:
        resultados_pop.append({
            "lote": i // LOTE + 1,
            "municipios_inicio": i + 1,
            "municipios_fim": i + len(lote),
            "dados": dados_lote
        })
        # Contar municípios com dados neste lote
        n_series = 0
        for var_obj in dados_lote:
            for res in var_obj.get("resultados", []):
                n_series += len(res.get("series", []))
        print(f"    OK — {n_series} séries retornadas")
    else:
        erros_pop.append({"lote": i // LOTE + 1, "erro": erro, "codigos": lote})
    time.sleep(SLEEP_BETWEEN)

out_pop = {
    "coletado_em": now_iso(),
    "fonte": f"{BASE_IBGE_V3}/agregados/9514/periodos/2022/variaveis/93",
    "tabela": "9514",
    "variavel": "93 (População residente - Censo 2022)",
    "total_lotes": len(resultados_pop),
    "erros": erros_pop,
    "dados": resultados_pop
}
with open("/home/user/workspace/sc-inteligencia/raw/ibge/populacao_sc.json", "w", encoding="utf-8") as f:
    json.dump(out_pop, f, ensure_ascii=False, indent=2)

# Contar municípios com dados
total_mun_pop = sum(
    len(res.get("series", []))
    for lote in resultados_pop
    for var_obj in lote["dados"]
    for res in var_obj.get("resultados", [])
)
print(f"  Salvos {len(resultados_pop)} lotes, ~{total_mun_pop} municípios com dados, {len(erros_pop)} erros")

# ─────────────────────────────────────────────────────────────
# TAREFA 3 — PIB Municipal 2021 (tabela 5938, variável 37)
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 3: PIB Municipal 2021 (tabela 5938, variável 37)")

resultados_pib = []
erros_pib = []

for i in range(0, len(codigos), LOTE):
    lote = codigos[i:i+LOTE]
    cods_pipe = "|".join(lote)
    url_pib = (
        f"{BASE_IBGE_V3}/agregados/5938/periodos/2021/variaveis/37"
        f"?localidades=N6[{cods_pipe}]"
    )
    print(f"  Lote {i//LOTE + 1}/{(len(codigos)-1)//LOTE + 1}: municípios {i+1}–{i+len(lote)}")
    dados_lote, erro = get_json(url_pib, f"pib_lote_{i//LOTE+1}")
    if dados_lote:
        resultados_pib.append({
            "lote": i // LOTE + 1,
            "municipios_inicio": i + 1,
            "municipios_fim": i + len(lote),
            "dados": dados_lote
        })
        n_series = sum(
            len(res.get("series", []))
            for var_obj in dados_lote
            for res in var_obj.get("resultados", [])
        )
        print(f"    OK — {n_series} séries retornadas")
    else:
        erros_pib.append({"lote": i // LOTE + 1, "erro": erro, "codigos": lote})
    time.sleep(SLEEP_BETWEEN)

out_pib = {
    "coletado_em": now_iso(),
    "fonte": f"{BASE_IBGE_V3}/agregados/5938/periodos/2021/variaveis/37",
    "tabela": "5938",
    "variavel": "37 (PIB a preços correntes - Mil Reais)",
    "modo": "lotes",
    "total_lotes": len(resultados_pib),
    "erros": erros_pib,
    "dados": resultados_pib
}
with open("/home/user/workspace/sc-inteligencia/raw/ibge/pib_sc.json", "w", encoding="utf-8") as f:
    json.dump(out_pib, f, ensure_ascii=False, indent=2)

total_mun_pib = sum(
    len(res.get("series", []))
    for lote in resultados_pib
    for var_obj in lote["dados"]
    for res in var_obj.get("resultados", [])
)
print(f"  Salvos {len(resultados_pib)} lotes, ~{total_mun_pib} municípios com dados, {len(erros_pib)} erros")

# ─────────────────────────────────────────────────────────────
# TAREFA 4 — BrasilAPI CNPJ Prefeituras SC
# Fonte: SICONFI (Secretaria do Tesouro Nacional) para CNPJs reais
# + BrasilAPI para dados cadastrais detalhados de cada CNPJ
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 4: CNPJs Prefeituras SC (SICONFI + BrasilAPI)")

# PASSO 4a: Obter CNPJs das prefeituras SC via SICONFI (Tesouro Nacional)
print("  4a: Obtendo CNPJs das prefeituras via SICONFI...")
url_siconfi = f"{BASE_SICONFI}/entes"
dados_siconfi_raw, erro_siconfi = get_json(url_siconfi, "siconfi_entes")

cnpj_por_ibge = {}
if dados_siconfi_raw:
    items = dados_siconfi_raw.get("items", [])
    sc_items = [x for x in items if str(x.get("uf", "")) == "SC"]
    print(f"  4a: {len(sc_items)} municípios SC encontrados no SICONFI")
    for item in sc_items:
        cod = str(item.get("cod_ibge", ""))
        cnpj = str(item.get("cnpj", "")).strip()
        if cnpj:
            cnpj_por_ibge[cod] = cnpj
    print(f"  4a: {len(cnpj_por_ibge)} CNPJs mapeados")
else:
    print(f"  4a: FALHA no SICONFI: {erro_siconfi}")

# Salvar mapeamento SICONFI como referência
out_siconfi_map = {
    "coletado_em": now_iso(),
    "fonte": url_siconfi,
    "nota": "Dados do SICONFI (Secretaria do Tesouro Nacional) - CNPJs das prefeituras",
    "dados": dados_siconfi_raw.get("items", []) if dados_siconfi_raw else []
}
with open("/home/user/workspace/sc-inteligencia/raw/brasilapi/siconfi_entes_sc.json", "w", encoding="utf-8") as f:
    json.dump(out_siconfi_map, f, ensure_ascii=False, indent=2)

time.sleep(SLEEP_BETWEEN)

# PASSO 4b: Para cada município SC, buscar dados CNPJ na BrasilAPI
print(f"  4b: Buscando dados CNPJ na BrasilAPI para {len(cnpj_por_ibge)} municípios...")
resultados_cnpj = []
erros_cnpj = []
municipios_sem_cnpj = []

for mun in municipios:
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
    time.sleep(SLEEP_BETWEEN)

print(f"  4b: Coletados={len(resultados_cnpj)}, erros={len(erros_cnpj)}, sem CNPJ={len(municipios_sem_cnpj)}")

out_cnpj = {
    "coletado_em": now_iso(),
    "fonte_cnpj": f"{BASE_BRASIL_API}/cnpj/v1/{{cnpj}}",
    "fonte_mapa_cnpj": url_siconfi,
    "nota": (
        "CNPJs obtidos do SICONFI (Tesouro Nacional). "
        "Dados cadastrais detalhados via BrasilAPI /cnpj/v1/."
    ),
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
        lotes = conteudo.get("total_lotes", 0)
        erros = len(conteudo.get("erros", []))
        muns = sum(
            len(res.get("series", []))
            for lote in conteudo.get("dados", [])
            for var_obj in lote.get("dados", [])
            for res in var_obj.get("resultados", [])
        )
        print(f"  {nome}: {lotes} lotes, ~{muns} municípios com dados, {erros} erros | {size/1024:.1f} KB")
    elif tipo == "pib":
        lotes = conteudo.get("total_lotes", 0)
        erros = len(conteudo.get("erros", []))
        muns = sum(
            len(res.get("series", []))
            for lote in conteudo.get("dados", [])
            for var_obj in lote.get("dados", [])
            for res in var_obj.get("resultados", [])
        )
        print(f"  {nome}: {lotes} lotes, ~{muns} municípios com dados, {erros} erros | {size/1024:.1f} KB")
    elif tipo == "cnpj":
        coletados = conteudo.get("cnpjs_coletados", 0)
        total = conteudo.get("total_municipios", 0)
        erros = len(conteudo.get("erros", []))
        print(f"  {nome}: {coletados}/{total} CNPJs coletados, {erros} erros | {size/1024:.1f} KB")
    elif tipo == "siconfi":
        n = len([x for x in conteudo.get("dados", []) if str(x.get("uf","")) == "SC"])
        print(f"  {nome}: {n} municípios SC | {size/1024:.1f} KB")

print("=" * 60)
print("Coleta concluída!")
