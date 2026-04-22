#!/usr/bin/env python3
"""
Coleta de dados da Câmara dos Deputados e Senado Federal para Santa Catarina.
"""

import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

BASE_CAMARA = "https://dadosabertos.camara.leg.br/api/v2"
BASE_SENADO = "https://legis.senado.leg.br/dadosabertos"

RAW = Path("/home/user/workspace/sc-inteligencia/raw")
RAW_CAMARA = RAW / "camara"
RAW_SENADO = RAW / "senado"

HEADERS_CAMARA = {"Accept": "application/json"}
HEADERS_SENADO = {"Accept": "application/json"}

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


def save(path, fonte, dados):
    obj = {
        "coletado_em": now_iso(),
        "fonte": fonte,
        "dados": dados
    }
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    size_kb = path.stat().st_size / 1024
    print(f"  [SAVED] {path.name} ({size_kb:.1f} KB)")


# ─────────────────────────────────────────────
# TAREFA 1 — Deputados SC legislatura 57
# ─────────────────────────────────────────────
print("\n=== TAREFA 1: Deputados SC (legislatura 57) ===")
url_dep = f"{BASE_CAMARA}/deputados"
# Note: usar sem 'itens=100' para evitar 504; a API retorna todos por padrão
params_dep = {"idLegislatura": 57, "siglaUf": "SC"}
data, err = get_json(url_dep, headers=HEADERS_CAMARA, params=params_dep)
time.sleep(SLEEP)

deputados = []
if err:
    print(f"  [ERRO] {err}")
    resultado_t1 = {"erro": err, "url": url_dep}
    save(RAW_CAMARA / "deputados_sc.json", url_dep, resultado_t1)
else:
    deputados_raw = data.get("dados", [])
    # Deduplica por id (alguns deputados aparecem em mais de um partido)
    seen = set()
    for d in deputados_raw:
        if d["id"] not in seen:
            seen.add(d["id"])
            deputados.append(d)
    print(f"  Retornados: {len(deputados_raw)} entradas, únicos: {len(deputados)} deputados")
    for d in deputados:
        print(f"    {d['id']} - {d['nome']} ({d['siglaPartido']})")
    save(RAW_CAMARA / "deputados_sc.json", url_dep, deputados)

ids_deputados = [d["id"] for d in deputados]

# ─────────────────────────────────────────────
# TAREFA 2 — Perfil completo de cada deputado
# ─────────────────────────────────────────────
print("\n=== TAREFA 2: Perfis completos ===")
perfis = []
for dep_id in ids_deputados:
    url = f"{BASE_CAMARA}/deputados/{dep_id}"
    data, err = get_json(url, headers=HEADERS_CAMARA)
    time.sleep(SLEEP)
    if err:
        print(f"  [ERRO] deputado {dep_id}: {err}")
        perfis.append({"erro": err, "url": url, "id": dep_id})
    else:
        perfil = data.get("dados", {})
        nome = perfil.get("nomeCivil", perfil.get("nome", str(dep_id)))
        partido = perfil.get("ultimoStatus", {}).get("siglaPartido", "?")
        print(f"  Perfil: {nome} ({partido})")
        perfis.append(perfil)

save(RAW_CAMARA / "perfis_deputados_sc.json",
     f"{BASE_CAMARA}/deputados/{{id}}", perfis)

# ─────────────────────────────────────────────
# TAREFA 3 — Emendas dos deputados SC
# ─────────────────────────────────────────────
print("\n=== TAREFA 3: Emendas dos deputados SC ===")
emendas_result = []

for dep_id in ids_deputados:
    dep_nome = next((d.get("nome", str(dep_id)) for d in deputados if d["id"] == dep_id), str(dep_id))

    # Mandatos
    url_mandatos = f"{BASE_CAMARA}/deputados/{dep_id}/mandatos"
    data_m, err_m = get_json(url_mandatos, headers=HEADERS_CAMARA)
    time.sleep(SLEEP)
    mandatos = data_m.get("dados", []) if not err_m else {"erro": err_m, "url": url_mandatos}

    # Proposições tipo EMC
    url_emc = f"{BASE_CAMARA}/proposicoes"
    params_emc = {"siglaTipo": "EMC", "idDeputadoAutor": dep_id, "itens": 100}
    data_e, err_e = get_json(url_emc, headers=HEADERS_CAMARA, params=params_emc)
    time.sleep(SLEEP)
    emendas = data_e.get("dados", []) if not err_e else {"erro": err_e, "url": url_emc}

    n_mandatos = len(mandatos) if isinstance(mandatos, list) else "erro"
    n_emendas = len(emendas) if isinstance(emendas, list) else "erro"
    print(f"  {dep_nome}: mandatos={n_mandatos}, EMC={n_emendas}")

    emendas_result.append({
        "id": dep_id,
        "nome": dep_nome,
        "mandatos": mandatos,
        "emendas_emc": emendas
    })

save(RAW_CAMARA / "emendas_deputados_sc.json",
     f"{BASE_CAMARA}/proposicoes?siglaTipo=EMC&idDeputadoAutor={{id}}",
     emendas_result)

# ─────────────────────────────────────────────
# TAREFA 4 — CEAP 2024
# ─────────────────────────────────────────────
print("\n=== TAREFA 4: CEAP 2024 ===")
ceap_result = []

for dep_id in ids_deputados:
    dep_nome = next((d.get("nome", str(dep_id)) for d in deputados if d["id"] == dep_id), str(dep_id))
    url_ceap = f"{BASE_CAMARA}/deputados/{dep_id}/despesas"
    params_ceap = {"ano": 2024, "itens": 100}
    data_c, err_c = get_json(url_ceap, headers=HEADERS_CAMARA, params=params_ceap)
    time.sleep(SLEEP)

    if err_c:
        print(f"  [ERRO] {dep_nome}: {err_c}")
        despesas = {"erro": err_c, "url": url_ceap}
    else:
        despesas = data_c.get("dados", [])
        total = sum(float(d.get("valorLiquido", 0) or 0) for d in despesas)
        print(f"  {dep_nome}: {len(despesas)} lançamentos, total R$ {total:,.2f}")

    ceap_result.append({
        "id": dep_id,
        "nome": dep_nome,
        "despesas_2024": despesas
    })

save(RAW_CAMARA / "ceap_sc_2024.json",
     f"{BASE_CAMARA}/deputados/{{id}}/despesas?ano=2024",
     ceap_result)

# ─────────────────────────────────────────────
# TAREFA 5 — Senadores SC
# ─────────────────────────────────────────────
print("\n=== TAREFA 5: Senadores SC ===")
url_senado_lista = f"{BASE_SENADO}/senador/lista/atual"
data_s, err_s = get_json(url_senado_lista, headers=HEADERS_SENADO)
time.sleep(SLEEP)

senadores_sc = []
if err_s:
    print(f"  [ERRO] {err_s}")
    save(RAW_SENADO / "senadores_sc.json", url_senado_lista,
         {"erro": err_s, "url": url_senado_lista})
else:
    try:
        lista_parlamentar = (
            data_s
            .get("ListaParlamentarEmExercicio", {})
            .get("Parlamentares", {})
            .get("Parlamentar", [])
        )
    except Exception:
        lista_parlamentar = []

    print(f"  Total senadores em exercício: {len(lista_parlamentar)}")

    for sen in lista_parlamentar:
        try:
            uf = (
                sen.get("IdentificacaoParlamentar", {})
                   .get("UfParlamentar", "")
            )
            if uf.upper() == "SC":
                senadores_sc.append(sen)
        except Exception:
            pass

    print(f"  Senadores SC encontrados: {len(senadores_sc)}")
    for s in senadores_sc:
        nome = s.get("IdentificacaoParlamentar", {}).get("NomeParlamentar", "?")
        codigo = s.get("IdentificacaoParlamentar", {}).get("CodigoParlamentar", "?")
        print(f"    - {nome} (código: {codigo})")

    save(RAW_SENADO / "senadores_sc.json", url_senado_lista, senadores_sc)

# ─────────────────────────────────────────────
# TAREFA 6 — Emendas dos senadores SC
# ─────────────────────────────────────────────
print("\n=== TAREFA 6: Emendas dos senadores SC ===")
emendas_senadores = []

for sen in senadores_sc:
    ident = sen.get("IdentificacaoParlamentar", {})
    codigo = ident.get("CodigoParlamentar", "")
    nome_sen = ident.get("NomeParlamentar", str(codigo))

    url_orc = f"{BASE_SENADO}/senador/{codigo}/orcamento"
    data_o, err_o = get_json(url_orc, headers=HEADERS_SENADO)
    time.sleep(SLEEP)

    if err_o:
        print(f"  [ERRO] {nome_sen} (código {codigo}): HTTP {err_o}")
        orcamento = {"erro": err_o, "url": url_orc}
    else:
        orcamento = data_o
        # Contar emendas se possível
        try:
            n = len(orcamento.get("EmendaParlamentar", {}).get("Emendas", {}).get("Emenda", []))
            print(f"  {nome_sen}: {n} emendas orçamentárias")
        except Exception:
            print(f"  {nome_sen}: dados orçamentários coletados (estrutura variável)")

    emendas_senadores.append({
        "codigo": codigo,
        "nome": nome_sen,
        "orcamento": orcamento
    })

save(RAW_SENADO / "emendas_senadores_sc.json",
     f"{BASE_SENADO}/senador/{{codigo}}/orcamento",
     emendas_senadores)

# ─────────────────────────────────────────────
# RESUMO FINAL
# ─────────────────────────────────────────────
print("\n" + "="*50)
print("RESUMO DA COLETA")
print("="*50)
print(f"Deputados SC encontrados:     {len(deputados)}")
print(f"Perfis coletados:             {len(perfis)}")
print(f"Entradas de emendas (câmara): {len(emendas_result)}")
print(f"Entradas CEAP 2024:           {len(ceap_result)}")
print(f"Senadores SC encontrados:     {len(senadores_sc)}")
print(f"Emendas senadores coletadas:  {len(emendas_senadores)}")
print("\nArquivos gerados:")
for f in sorted(list(RAW_CAMARA.glob("*.json")) + list(RAW_SENADO.glob("*.json"))):
    size_kb = f.stat().st_size / 1024
    rel = str(f).replace(str(RAW.parent) + "/", "")
    print(f"  {rel:<65} {size_kb:>8.1f} KB")
print("\nColeta finalizada:", now_iso())
