#!/usr/bin/env python3
"""
Coleta de emendas parlamentares SC - Portal da Transparência
"""

import requests
import json
import time
from datetime import datetime
import os

API_KEY = "88515372af5a0fbca47c4954e40716b7"
HEADERS = {"chave-api-dados": API_KEY}
BASE_DIR = "/home/user/workspace/sc-inteligencia/raw/transparencia"
BASE_URL = "https://api.portaldatransparencia.gov.br/api-de-dados"

os.makedirs(BASE_DIR, exist_ok=True)


def get_with_retry(url, params=None, max_retries=5):
    """GET request com retry em caso de rate limit"""
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
                print(f"  Resposta: {resp.text[:300]}")
                return None
        except Exception as e:
            print(f"  [EXCEPTION] {e} - tentativa {attempt+1}")
            time.sleep(5)
    return None


# =============================================================================
# TAREFA 1 — Emendas por ano (2020-2024)
# =============================================================================
print("=" * 60)
print("TAREFA 1 — Emendas parlamentares SC por ano (2020-2024)")
print("=" * 60)

anos = [2020, 2021, 2022, 2023, 2024]
resumo_geral = {}

for ano in anos:
    print(f"\n--- Ano {ano} ---")
    todas_emendas = []
    pagina = 1
    coletado_em = datetime.utcnow().isoformat() + "Z"
    fonte_base = f"{BASE_URL}/emendas?codigoFuncao=&uf=SC&ano={ano}"

    while True:
        params = {
            "codigoFuncao": "",
            "uf": "SC",
            "ano": ano,
            "pagina": pagina
        }
        dados = get_with_retry(f"{BASE_URL}/emendas", params=params)

        if dados is None:
            print(f"  Página {pagina}: resposta nula, encerrando.")
            break

        # Aceita lista ou dict com chave 'data'/'dados'
        if isinstance(dados, list):
            registros = dados
        elif isinstance(dados, dict):
            registros = dados.get("data", dados.get("dados", []))
        else:
            registros = []

        if not registros:
            print(f"  Página {pagina}: vazia, encerrando paginação.")
            break

        todas_emendas.extend(registros)

        if pagina % 10 == 0:
            print(f"  Progresso: página {pagina}, total até agora: {len(todas_emendas)}")

        if len(registros) < 100:
            print(f"  Página {pagina}: {len(registros)} registros (< 100), fim da paginação.")
            break

        pagina += 1
        time.sleep(0.5)

    total = len(todas_emendas)
    resumo_geral[ano] = total
    print(f"  Total coletado para {ano}: {total} emendas")

    saida = {
        "coletado_em": coletado_em,
        "fonte": fonte_base,
        "ano": ano,
        "total_registros": total,
        "dados": todas_emendas
    }

    caminho = os.path.join(BASE_DIR, f"emendas_sc_{ano}.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    print(f"  Salvo em: {caminho}")
    time.sleep(1)

print("\n=== RESUMO TAREFA 1 ===")
for ano, total in resumo_geral.items():
    print(f"  {ano}: {total} emendas")


# =============================================================================
# TAREFA 2 — Emendas sem município
# =============================================================================
print("\n" + "=" * 60)
print("TAREFA 2 — Emendas sem município (múltiplo/sem IBGE)")
print("=" * 60)

emendas_sem_municipio = []
localidades_multiplas = {"Santa Catarina", "Múltiplo", "múltiplo", "MÚLTIPLO", "Multiplo", "MULTIPLO"}

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
        # Campos possíveis dependendo da API
        localidade = (
            emenda.get("localidade") or
            emenda.get("localidadeDoGasto") or
            emenda.get("municipio") or
            ""
        )
        cod_ibge = (
            emenda.get("codigoMunicipioIBGE") or
            emenda.get("codigoIbge") or
            emenda.get("ibge") or
            None
        )
        numero = (
            emenda.get("numeroEmenda") or
            emenda.get("numero") or
            emenda.get("id") or
            None
        )

        # Verificar condição
        localidade_str = str(localidade).strip() if localidade else ""
        is_multiplo = localidade_str in localidades_multiplas or localidade_str.lower() in {"múltiplo", "multiplo", "santa catarina"}
        sem_ibge = not cod_ibge or cod_ibge in [None, "", "null", 0]

        if is_multiplo or sem_ibge:
            registro = {
                "ano": ano,
                "numeroEmenda": numero,
                "localidade": localidade_str,
                "codigoMunicipioIBGE": cod_ibge,
                "autor": emenda.get("autor") or emenda.get("nomeAutor") or emenda.get("nomeEmendamento"),
                "valorEmpenhado": emenda.get("valorEmpenhado") or emenda.get("empenhado"),
                "valorLiquidado": emenda.get("valorLiquidado") or emenda.get("liquidado"),
                "valorPago": emenda.get("valorPago") or emenda.get("pago"),
            }
            emendas_sem_municipio.append(registro)
            count_ano += 1

    print(f"  {ano}: {count_ano} emendas sem município definido")

print(f"\n  Total geral sem município: {len(emendas_sem_municipio)}")

saida_sem_municipio = {
    "coletado_em": datetime.utcnow().isoformat() + "Z",
    "fonte": "Análise dos arquivos emendas_sc_YYYY.json",
    "descricao": "Emendas onde localidade é 'Santa Catarina', 'Múltiplo' ou codigoMunicipioIBGE é nulo",
    "total_registros": len(emendas_sem_municipio),
    "dados": emendas_sem_municipio
}

caminho_sem_mun = os.path.join(BASE_DIR, "emendas_sem_municipio_sc.json")
with open(caminho_sem_mun, "w", encoding="utf-8") as f:
    json.dump(saida_sem_municipio, f, ensure_ascii=False, indent=2)

print(f"  Salvo em: {caminho_sem_mun}")


# =============================================================================
# TAREFA 3 — Empenhos por UF SC 2024
# =============================================================================
print("\n" + "=" * 60)
print("TAREFA 3 — Empenhos por UF SC 2024")
print("=" * 60)

url_uf = f"{BASE_URL}/emendas/por-uf"
params_uf = {"uf": "SC", "ano": 2024}
coletado_em_uf = datetime.utcnow().isoformat() + "Z"

dados_uf = get_with_retry(url_uf, params=params_uf)

if dados_uf is None:
    print("  Falha ao coletar empenhos por UF.")
    dados_uf = []

if isinstance(dados_uf, list):
    registros_uf = dados_uf
elif isinstance(dados_uf, dict):
    registros_uf = dados_uf.get("data", dados_uf.get("dados", [dados_uf]))
else:
    registros_uf = []

print(f"  Registros retornados: {len(registros_uf) if isinstance(registros_uf, list) else 1}")

saida_uf = {
    "coletado_em": coletado_em_uf,
    "fonte": f"{url_uf}?uf=SC&ano=2024",
    "total_registros": len(registros_uf) if isinstance(registros_uf, list) else 1,
    "dados": registros_uf
}

caminho_uf = os.path.join(BASE_DIR, "empenhos_uf_sc_2024.json")
with open(caminho_uf, "w", encoding="utf-8") as f:
    json.dump(saida_uf, f, ensure_ascii=False, indent=2)

print(f"  Salvo em: {caminho_uf}")

# =============================================================================
# RESUMO FINAL
# =============================================================================
print("\n" + "=" * 60)
print("RESUMO FINAL DA COLETA")
print("=" * 60)
for ano, total in resumo_geral.items():
    print(f"  emendas_sc_{ano}.json          : {total} emendas")
print(f"  emendas_sem_municipio_sc.json  : {len(emendas_sem_municipio)} registros")
print(f"  empenhos_uf_sc_2024.json       : {saida_uf['total_registros']} registros")
print("\nColeta concluída!")
