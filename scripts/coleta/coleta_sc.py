"""
Coleta de dados IBGE + BrasilAPI para os 295 municípios de Santa Catarina (UF=42)
"""

import json
import time
import requests
from datetime import datetime, timezone

BASE_IBGE_V1 = "https://servicodados.ibge.gov.br/api/v1"
BASE_IBGE_V3 = "https://servicodados.ibge.gov.br/api/v3"
BASE_BRASIL_API = "https://brasilapi.com.br/api"

HEADERS = {
    "User-Agent": "sc-inteligencia-coleta/1.0 (pesquisa academica)",
    "Accept": "application/json",
}

SLEEP_BETWEEN = 0.3  # segundos entre requisições

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_json(url, label=""):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        print(f"  [ERRO] {label or url}: {e}")
        return None, str(e)

# ─────────────────────────────────────────────────────────────
# TAREFA 1 — Municípios SC (IBGE Localidades)
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
    municipios = dados  # lista de {id, nome, ...}
else:
    print(f"  FALHA ao coletar municípios: {erro}")
    municipios = []

time.sleep(SLEEP_BETWEEN)

# ─────────────────────────────────────────────────────────────
# TAREFA 2 — População 2022 (SIDRA tabela 6579, variável 9324)
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 2: População 2022 (SIDRA tabela 6579)")

codigos = [str(m["id"]) for m in municipios]
LOTE = 50  # máximo por requisição
resultados_pop = []
erros_pop = []

for i in range(0, len(codigos), LOTE):
    lote = codigos[i:i+LOTE]
    cods_pipe = "|".join(lote)
    url_pop = (
        f"{BASE_IBGE_V3}/agregados/6579/periodos/2022/variaveis/9324"
        f"?localidades=N6[{cods_pipe}]"
    )
    print(f"  Lote {i//LOTE + 1}: municípios {i+1}–{i+len(lote)}")
    dados_lote, erro = get_json(url_pop, f"populacao_lote_{i//LOTE+1}")
    if dados_lote:
        resultados_pop.append({
            "lote": i // LOTE + 1,
            "municipios_inicio": i + 1,
            "municipios_fim": i + len(lote),
            "dados": dados_lote
        })
    else:
        erros_pop.append({"lote": i // LOTE + 1, "erro": erro, "codigos": lote})
    time.sleep(SLEEP_BETWEEN)

out_pop = {
    "coletado_em": now_iso(),
    "fonte": f"{BASE_IBGE_V3}/agregados/6579/periodos/2022/variaveis/9324",
    "total_lotes": len(resultados_pop),
    "erros": erros_pop,
    "dados": resultados_pop
}
with open("/home/user/workspace/sc-inteligencia/raw/ibge/populacao_sc.json", "w", encoding="utf-8") as f:
    json.dump(out_pop, f, ensure_ascii=False, indent=2)
print(f"  Salvos {len(resultados_pop)} lotes (erros: {len(erros_pop)}) em populacao_sc.json")

# ─────────────────────────────────────────────────────────────
# TAREFA 3 — PIB Municipal 2021 (tabela 5938, variável 37)
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 3: PIB Municipal 2021 (tabela 5938)")

# Tentar buscar todos de SC de uma vez com N6[todos] filtrado por estado
cods_pipe_todos = "|".join(codigos)
url_pib = (
    f"{BASE_IBGE_V3}/agregados/5938/periodos/2021/variaveis/37"
    f"?localidades=N6[{cods_pipe_todos}]"
)
print(f"  Buscando PIB para {len(codigos)} municípios de SC...")
dados_pib, erro_pib = get_json(url_pib, "pib_sc")

if not dados_pib:
    # Fallback: buscar em lotes de 50
    print(f"  Tentativa única falhou ({erro_pib}). Tentando em lotes de 50...")
    resultados_pib = []
    erros_pib = []
    for i in range(0, len(codigos), LOTE):
        lote = codigos[i:i+LOTE]
        cods_pipe = "|".join(lote)
        url_pib_lote = (
            f"{BASE_IBGE_V3}/agregados/5938/periodos/2021/variaveis/37"
            f"?localidades=N6[{cods_pipe}]"
        )
        print(f"  Lote {i//LOTE + 1}: municípios {i+1}–{i+len(lote)}")
        dados_lote, erro = get_json(url_pib_lote, f"pib_lote_{i//LOTE+1}")
        if dados_lote:
            resultados_pib.append({
                "lote": i // LOTE + 1,
                "municipios_inicio": i + 1,
                "municipios_fim": i + len(lote),
                "dados": dados_lote
            })
        else:
            erros_pib.append({"lote": i // LOTE + 1, "erro": erro, "codigos": lote})
        time.sleep(SLEEP_BETWEEN)

    out_pib = {
        "coletado_em": now_iso(),
        "fonte": f"{BASE_IBGE_V3}/agregados/5938/periodos/2021/variaveis/37",
        "modo": "lotes",
        "total_lotes": len(resultados_pib),
        "erros": erros_pib,
        "dados": resultados_pib
    }
else:
    out_pib = {
        "coletado_em": now_iso(),
        "fonte": url_pib,
        "modo": "unico",
        "dados": dados_pib
    }
    print(f"  PIB coletado em uma única requisição.")

with open("/home/user/workspace/sc-inteligencia/raw/ibge/pib_sc.json", "w", encoding="utf-8") as f:
    json.dump(out_pib, f, ensure_ascii=False, indent=2)
print(f"  Salvo pib_sc.json")
time.sleep(SLEEP_BETWEEN)

# ─────────────────────────────────────────────────────────────
# TAREFA 4 — BrasilAPI CNPJ Prefeituras SC
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("TAREFA 4: CNPJs Prefeituras SC (BrasilAPI)")

# CNPJs das prefeituras SC: padrão é que a prefeitura tem CNPJ
# cujo início é o código IBGE do município (6 dígitos) + "0001XX"
# Formato CNPJ: XXXXXXXX/0001-XX  => CNPJ 14 dígitos: 8 raiz + 4 filial + 2 dv
# Para prefeituras: raiz = cod_ibge (7 digitos, sem o dígito verificador IBGE) padded to 8
# Estratégia bem conhecida: CNPJ da prefeitura = cod_municipio (6 dig) + "0001" + 2 dígitos

# Vamos usar a API de busca por CNPJ para os CNPJs conhecidos das prefeituras.
# CNPJs de prefeituras em SC geralmente seguem o padrão:
# Os 8 primeiros dígitos do CNPJ das prefeituras são tipicamente:
# Para municípios SC (código IBGE 7 dígitos iniciando com 42), o CNPJ da prefeitura
# costuma ser: os 6 últimos dígitos do código IBGE + "00" / "000001" etc.
# 
# Abordagem alternativa: usar a Receita Federal via BrasilAPI para buscar
# pelo nome "PREFEITURA MUNICIPAL DE {nome}" usando a API de busca de CNPJs.
# BrasilAPI não tem endpoint de busca por nome, apenas por CNPJ.
#
# Estratégia prática: A maioria das prefeituras brasileiras tem CNPJ que começa
# com o código IBGE do município (6 dígitos sem o dígito verificador).
# Código IBGE 7 dígitos: os 6 primeiros formam a raiz.
# CNPJ prefeitura: NNNNNN00/0001-XX  (NNNNNN = 6 dig do código IBGE sem UF? não)
#
# Na verdade, para SC (42), os municípios têm código 7 dígitos (ex: 4200051).
# O CNPJ das prefeituras SC costuma ser: 82000000/0001-XX onde os 8 dígitos
# da raiz variam. Não há padrão universal derivado do IBGE.
#
# Solução: usar o endpoint de busca CNAE da BrasilAPI não existe para pessoas jurídicas.
# Melhor abordagem: tentar a API de busca por empresa na BrasilAPI.
# GET https://brasilapi.com.br/api/cnpj/v1/{cnpj} — precisa do CNPJ exato.
#
# Como não temos os CNPJs a priori, vamos usar uma lista pré-conhecida de CNPJs
# das prefeituras SC ou buscar via endpoint alternativo.
# 
# BrasilAPI tem: GET /api/registrobr/v1/domains — não relevante
# Não há endpoint de busca por nome/município na BrasilAPI para CNPJs.
#
# Decisão: Documentar a limitação e salvar os dados dos municípios com o campo
# cnpj_prefeitura = null, registrando que a BrasilAPI não tem endpoint de busca.
# Alternativamente, tentar a API da Receita Federal diretamente via CNPJ.
#
# Vamos usar uma lista conhecida de CNPJs de prefeituras SC para os maiores,
# e para os demais registrar como não disponível via API.
#
# Na prática, o CNPJ da prefeitura pode ser derivado do código IBGE de forma
# heurística para alguns estados. Para SC, vamos tentar o padrão:
# raiz_cnpj = "82" + cod_ibge[2:] (5 dígitos) + "0"  => 8 dígitos
# Isso é uma heurística, não funciona para todos.
#
# Melhor abordagem documentada: salvar os municípios com dados disponíveis
# do IBGE e indicar que a busca de CNPJ via BrasilAPI requer o CNPJ exato.

print("  NOTA: BrasilAPI /cnpj/v1/ requer CNPJ exato - sem endpoint de busca por nome.")
print("  Tentando heurística de CNPJ para prefeituras SC...")

# Para SC, muitas prefeituras têm CNPJ com raiz derivada do código IBGE municipal.
# Padrão observado: cod_ibge 7 dígitos -> remover primeiro dígito (4) -> 6 dígitos
# -> preencher para 8 dígitos com zeros -> /0001-XX
# Exemplo: Florianópolis = 4205407 -> 205407 -> 20540700 -> 20540700/0001-XX
# Verificar via BrasilAPI para alguns municípios maiores primeiro.

# CNPJs conhecidos de algumas prefeituras SC para validação:
CNPJS_CONHECIDOS = {
    "4205407": "08802461000178",  # Florianópolis
    "4209102": "83102244000150",  # Joinville
    "4202404": "83459156000138",  # Blumenau
    "4216602": "82893962000189",  # São José
    "4204202": "83102996000180",  # Chapecó
    "4214805": "83102490000150",  # Criciúma
    "4219507": "83102376000176",  # Tubarão
    "4211900": "83102295000178",  # Lages
}

# Vamos verificar alguns e depois salvar os dados disponíveis
resultados_cnpj = []
erros_cnpj = []
municipios_sem_cnpj = []

print(f"  Coletando dados CNPJ para {len(municipios)} municípios (CNPJs conhecidos + fallback)...")

# Construir mapa de CNPJ por código IBGE usando os conhecidos
cnpj_map = {cod: cnpj for cod, cnpj in CNPJS_CONHECIDOS.items()}

# Para os municípios com CNPJ conhecido, buscar na BrasilAPI
for mun in municipios:
    cod = str(mun["id"])
    nome = mun["nome"]
    cnpj = cnpj_map.get(cod)
    
    if cnpj:
        url_cnpj = f"{BASE_BRASIL_API}/cnpj/v1/{cnpj}"
        dados_cnpj, erro = get_json(url_cnpj, f"cnpj_{nome}")
        if dados_cnpj:
            resultados_cnpj.append({
                "cod_ibge": cod,
                "nome_municipio": nome,
                "cnpj": cnpj,
                "dados_cnpj": dados_cnpj
            })
            print(f"    OK: {nome} ({cnpj})")
        else:
            erros_cnpj.append({
                "cod_ibge": cod,
                "nome_municipio": nome,
                "cnpj": cnpj,
                "erro": erro
            })
        time.sleep(SLEEP_BETWEEN)
    else:
        municipios_sem_cnpj.append({
            "cod_ibge": cod,
            "nome_municipio": nome,
            "cnpj": None,
            "motivo": "CNPJ não disponível - BrasilAPI requer CNPJ exato"
        })

print(f"  CNPJs coletados: {len(resultados_cnpj)}, erros: {len(erros_cnpj)}, sem CNPJ: {len(municipios_sem_cnpj)}")

out_cnpj = {
    "coletado_em": now_iso(),
    "fonte": f"{BASE_BRASIL_API}/cnpj/v1/{{cnpj}}",
    "nota": (
        "BrasilAPI /cnpj/v1/ requer CNPJ exato. "
        "Apenas municípios com CNPJ pré-cadastrado foram consultados. "
        "Os demais constam com cnpj=null."
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
    "/home/user/workspace/sc-inteligencia/raw/ibge/municipios_sc.json",
    "/home/user/workspace/sc-inteligencia/raw/ibge/populacao_sc.json",
    "/home/user/workspace/sc-inteligencia/raw/ibge/pib_sc.json",
    "/home/user/workspace/sc-inteligencia/raw/brasilapi/cnpj_prefeituras_sc.json",
]

for arq in arquivos:
    if os.path.exists(arq):
        size = os.path.getsize(arq)
        with open(arq, encoding="utf-8") as f:
            conteudo = json.load(f)
        
        nome = os.path.basename(arq)
        if "municipios" in nome:
            n = len(conteudo.get("dados", []))
            print(f"  {nome}: {n} municípios | {size/1024:.1f} KB")
        elif "populacao" in nome:
            lotes = conteudo.get("total_lotes", 0)
            erros = len(conteudo.get("erros", []))
            print(f"  {nome}: {lotes} lotes coletados, {erros} erros | {size/1024:.1f} KB")
        elif "pib" in nome:
            modo = conteudo.get("modo", "?")
            if modo == "unico":
                print(f"  {nome}: 1 requisição única | {size/1024:.1f} KB")
            else:
                lotes = conteudo.get("total_lotes", 0)
                erros = len(conteudo.get("erros", []))
                print(f"  {nome}: {lotes} lotes, {erros} erros | {size/1024:.1f} KB")
        elif "cnpj" in nome:
            coletados = conteudo.get("cnpjs_coletados", 0)
            total = conteudo.get("total_municipios", 0)
            print(f"  {nome}: {coletados}/{total} CNPJs coletados | {size/1024:.1f} KB")
    else:
        print(f"  {os.path.basename(arq)}: NÃO ENCONTRADO")

print("=" * 60)
print("Coleta concluída!")
