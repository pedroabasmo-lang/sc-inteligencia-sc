#!/usr/bin/env python3
"""
Coleta de emendas parlamentares SC - Portal da Transparência v2
Coleta TODAS as emendas de cada ano (API não suporta filtro de UF efetivo)
e filtra localmente por Santa Catarina.
"""

import requests
import json
import time
from datetime import datetime, timezone
import os

API_KEY = "88515372af5a0fbca47c4954e40716b7"
HEADERS = {"chave-api-dados": API_KEY}
BASE_DIR = "/home/user/workspace/sc-inteligencia/raw/transparencia"
BASE_URL = "https://api.portaldatransparencia.gov.br/api-de-dados"

# Termos que identificam SC como destino dos recursos
SC_LOCALIDADES = {
    "SANTA CATARINA (UF)",
    "SANTA CATARINA",
}

def is_sc(emenda):
    """Retorna True se a emenda tem destino Santa Catarina (UF ou município de SC)"""
    localidade = str(emenda.get("localidadeDoGasto") or "").upper().strip()
    # UF direta
    if localidade in ("SANTA CATARINA (UF)", "SANTA CATARINA"):
        return True
    # Município de SC: formato "NOME MUNICIPIO - SC"
    if localidade.endswith(" - SC") or localidade.endswith("- SC"):
        return True
    return False

def get_with_retry(url, params=None, max_retries=5):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if resp.status_code == 429:
                print(f"  [429] Rate limit. Aguardando 10s... (tentativa {attempt+1})")
                time.sleep(10)
                continue
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"  [ERRO {resp.status_code}] URL: {url} | Params: {params}")
                return None
        except Exception as e:
            print(f"  [EXCEPTION] {e} - tentativa {attempt+1}")
            time.sleep(5)
    return None


# ===========================================================================
# TAREFA 1 — Emendas por ano (2020-2024) - apenas registros SC
# ===========================================================================
print("=" * 65)
print("TAREFA 1 — Emendas parlamentares SC por ano (2020-2024)")
print("  (coletando todas, filtrando localidade Santa Catarina)")
print("=" * 65)

anos = [2020, 2021, 2022, 2023, 2024]
resumo_geral = {}

for ano in anos:
    print(f"\n--- Ano {ano} ---")
    todas_sc = []
    pagina = 1
    total_paginas = 0
    coletado_em = datetime.now(timezone.utc).isoformat()
    fonte_base = f"{BASE_URL}/emendas?ano={ano}&pagina={{pagina}}"

    while True:
        params = {"ano": ano, "pagina": pagina}
        dados = get_with_retry(f"{BASE_URL}/emendas", params=params)

        if dados is None:
            print(f"  Página {pagina}: resposta nula, encerrando.")
            break

        if isinstance(dados, list):
            registros = dados
        elif isinstance(dados, dict):
            registros = dados.get("data", dados.get("dados", []))
        else:
            registros = []

        if not registros:
            print(f"  Página {pagina}: vazia, encerrando paginação.")
            break

        total_paginas += 1
        # Filtrar SC
        sc_registros = [r for r in registros if is_sc(r)]
        todas_sc.extend(sc_registros)

        if pagina % 10 == 0:
            print(f"  Progresso: página {pagina}, registros SC até agora: {len(todas_sc)}")

        if len(registros) < 15:
            print(f"  Página {pagina}: {len(registros)} registros (< 15), fim da paginação.")
            break

        pagina += 1
        time.sleep(0.5)

    total = len(todas_sc)
    resumo_geral[ano] = {"total_sc": total, "total_paginas": pagina}
    print(f"  Total páginas: {pagina} | Registros SC: {total}")

    saida = {
        "coletado_em": coletado_em,
        "fonte": fonte_base,
        "ano": ano,
        "filtro": "localidadeDoGasto contém 'SANTA CATARINA' ou termina em '- SC'",
        "total_paginas_coletadas": pagina,
        "total_registros": total,
        "dados": todas_sc
    }

    caminho = os.path.join(BASE_DIR, f"emendas_sc_{ano}.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    print(f"  Salvo em: {caminho}")
    time.sleep(1)

print("\n=== RESUMO TAREFA 1 ===")
for ano, info in resumo_geral.items():
    print(f"  {ano}: {info['total_sc']} emendas SC (em {info['total_paginas']} páginas)")


# ===========================================================================
# TAREFA 2 — Emendas sem município definido
# ===========================================================================
print("\n" + "=" * 65)
print("TAREFA 2 — Emendas sem município (múltiplo/SC UF/sem IBGE)")
print("=" * 65)

emendas_sem_municipio = []

for ano in anos:
    caminho = os.path.join(BASE_DIR, f"emendas_sc_{ano}.json")
    if not os.path.exists(caminho):
        print(f"  Arquivo {caminho} não encontrado, pulando.")
        continue

    with open(caminho, "r", encoding="utf-8") as f:
        dados_ano = json.load(f)

    emendas = dados_ano.get("dados", [])
    count_ano = 0

    for emenda in emendas:
        localidade = str(emenda.get("localidadeDoGasto") or "").strip()
        
        # Sem município específico: é UF ou vazio
        sem_municipio = (
            localidade.upper() in ("SANTA CATARINA (UF)", "SANTA CATARINA", "") or
            localidade == "" or
            # Não tem municício específico (não tem " - SC" com cidade)
            (localidade.upper().endswith(" - SC") == False and "SANTA CATARINA" in localidade.upper())
        )

        if sem_municipio:
            registro = {
                "ano": ano,
                "codigoEmenda": emenda.get("codigoEmenda"),
                "numeroEmenda": emenda.get("numeroEmenda"),
                "tipoEmenda": emenda.get("tipoEmenda"),
                "nomeAutor": emenda.get("nomeAutor"),
                "localidadeDoGasto": localidade,
                "codigoMunicipioIBGE": None,  # Não retornado neste endpoint
                "valorEmpenhado": emenda.get("valorEmpenhado"),
                "valorLiquidado": emenda.get("valorLiquidado"),
                "valorPago": emenda.get("valorPago"),
            }
            emendas_sem_municipio.append(registro)
            count_ano += 1

    print(f"  {ano}: {len(emendas)} emendas SC, {count_ano} sem município específico")

print(f"\n  Total geral sem município: {len(emendas_sem_municipio)}")

saida_sem_municipio = {
    "coletado_em": datetime.now(timezone.utc).isoformat(),
    "fonte": "Análise dos arquivos emendas_sc_YYYY.json",
    "descricao": "Emendas onde localidadeDoGasto é 'SANTA CATARINA (UF)' ou 'SANTA CATARINA' (sem identificação de município específico)",
    "total_registros": len(emendas_sem_municipio),
    "dados": emendas_sem_municipio
}

caminho_sem_mun = os.path.join(BASE_DIR, "emendas_sem_municipio_sc.json")
with open(caminho_sem_mun, "w", encoding="utf-8") as f:
    json.dump(saida_sem_municipio, f, ensure_ascii=False, indent=2)

print(f"  Salvo em: {caminho_sem_mun}")


# ===========================================================================
# TAREFA 3 — Empenhos por UF SC 2024
# ===========================================================================
print("\n" + "=" * 65)
print("TAREFA 3 — Empenhos por UF SC 2024")
print("=" * 65)

# Tentar endpoint com diferentes variações
endpoints_uf = [
    f"{BASE_URL}/emendas/por-uf",
    f"{BASE_URL}/emendas/poruf",
    f"{BASE_URL}/emendas-por-uf",
]

dados_uf = None
url_usada = None

for ep in endpoints_uf:
    r = requests.get(ep, headers=HEADERS, params={"uf": "SC", "ano": 2024}, timeout=15)
    print(f"  {ep}: status {r.status_code}")
    if r.status_code == 200:
        dados_uf = r.json()
        url_usada = f"{ep}?uf=SC&ano=2024"
        break
    time.sleep(0.3)

if dados_uf is None:
    # Fallback: agregar dados do arquivo de 2024 por UF
    print("  Endpoint por-uf não disponível. Gerando agregação dos dados coletados...")
    caminho_2024 = os.path.join(BASE_DIR, "emendas_sc_2024.json")
    if os.path.exists(caminho_2024):
        with open(caminho_2024) as f:
            d24 = json.load(f)
        emendas_2024 = d24.get("dados", [])
        
        # Agregar
        def parse_val(v):
            try:
                return float(str(v).replace(".", "").replace(",", "."))
            except:
                return 0.0
        
        agg = {
            "uf": "SC",
            "ano": 2024,
            "total_emendas": len(emendas_2024),
            "valor_empenhado_total": sum(parse_val(e.get("valorEmpenhado", 0)) for e in emendas_2024),
            "valor_liquidado_total": sum(parse_val(e.get("valorLiquidado", 0)) for e in emendas_2024),
            "valor_pago_total": sum(parse_val(e.get("valorPago", 0)) for e in emendas_2024),
            "por_tipo": {},
            "por_funcao": {},
            "emendas": emendas_2024
        }
        
        for e in emendas_2024:
            tp = e.get("tipoEmenda", "N/A")
            agg["por_tipo"][tp] = agg["por_tipo"].get(tp, 0) + 1
            fn = e.get("funcao", "N/A")
            agg["por_funcao"][fn] = agg["por_funcao"].get(fn, 0) + 1
        
        dados_uf = agg
        url_usada = "Agregação a partir de emendas_sc_2024.json"
    else:
        dados_uf = {}
        url_usada = "N/A - dados não disponíveis"

saida_uf = {
    "coletado_em": datetime.now(timezone.utc).isoformat(),
    "fonte": url_usada,
    "total_registros": 1 if isinstance(dados_uf, dict) else len(dados_uf),
    "dados": dados_uf
}

caminho_uf = os.path.join(BASE_DIR, "empenhos_uf_sc_2024.json")
with open(caminho_uf, "w", encoding="utf-8") as f:
    json.dump(saida_uf, f, ensure_ascii=False, indent=2)

print(f"  Salvo em: {caminho_uf}")

# ===========================================================================
# RESUMO FINAL
# ===========================================================================
print("\n" + "=" * 65)
print("RESUMO FINAL DA COLETA")
print("=" * 65)
for ano, info in resumo_geral.items():
    print(f"  emendas_sc_{ano}.json          : {info['total_sc']} emendas SC")
print(f"  emendas_sem_municipio_sc.json  : {len(emendas_sem_municipio)} registros")
print(f"  empenhos_uf_sc_2024.json       : gerado")
print("\nColeta concluída com sucesso!")
