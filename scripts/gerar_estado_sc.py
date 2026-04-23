"""
Atualiza estado_sc.json com emendas reais do TransfereGov.

Estrutura esperada pelo painel:
  m.emendas = {
    empenhado: valor total,
    pago: 0 (não disponível no TransfereGov),
    n: número de emendas,
    parl: [lista de nomes dos parlamentares],
    areas: [{area: "Saúde", valor: 123456}, ...]
  }
"""

import json
import re
import csv
import unicodedata
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).parent.parent
RAW = BASE / "raw"
PAINEL = BASE.parent / "painel-wilson-sc"


def normalizar_nome(nome: str) -> str:
    """Remove acentos, converte para upper, trata D'OESTE."""
    nome = re.sub(r"D'OESTE", "DO OESTE", nome.upper())
    s = unicodedata.normalize("NFD", nome)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z0-9 ]", "", s.upper())
    return re.sub(r"\s+", " ", s).strip()


def extrair_area(descricao_areas: str | None) -> str:
    if not descricao_areas:
        return "Outros"
    areas_map = {
        "saude": "Saúde",
        "educacao": "Educação",
        "educação": "Educação",
        "assistencia": "Assistência Social",
        "infraestrutura": "Infraestrutura",
        "saneamento": "Saneamento",
        "urbanismo": "Urbanismo",
        "habitacao": "Habitação",
        "agricultura": "Agricultura",
        "esporte": "Esporte",
        "cultura": "Cultura",
        "seguranca": "Segurança",
        "meio ambiente": "Meio Ambiente",
        "energia": "Energia",
        "transporte": "Transporte",
    }
    desc_lower = descricao_areas.lower()
    for keyword, area_name in areas_map.items():
        if keyword in desc_lower:
            return area_name
    return "Outros"


def main():
    print("=== Atualizador estado_sc.json com emendas reais ===\n")

    # Carregar lookup de municípios
    por_nome_lookup = {}
    por_ibge = {}
    with open(BASE / "lookups" / "municipios_br.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("uf", "").upper() != "SC":
                continue
            cod = row["cod_ibge"]
            nome_norm = row["nome_normalizado"]
            por_nome_lookup[nome_norm] = cod
            por_ibge[cod] = row["nome"]
    print(f"Lookup: {len(por_nome_lookup)} municípios SC")

    # Carregar estado_sc.json
    estado_path = PAINEL / "estado_sc.json"
    estado = json.load(open(estado_path, encoding="utf-8"))
    por_id = {str(m["id"]): i for i, m in enumerate(estado)}
    por_nome = {normalizar_nome(m["nome"]): i for i, m in enumerate(estado)}
    print(f"Estado SC: {len(estado)} municípios carregados")

    # Carregar TransfereGov
    tgov_path = RAW / "transferegov" / "plano_acao_sc.json"
    d = json.load(open(tgov_path, encoding="utf-8"))
    records = d.get("data", [])
    print(f"TransfereGov: {len(records)} registros")

    # Construir emendas por cod_ibge
    emendas_por_munic = defaultdict(lambda: {
        "empenhado": 0.0,
        "n": 0,
        "parl": set(),
        "areas": defaultdict(float),
    })

    nao_resolvidos = 0
    for rec in records:
        nome_parlamentar = rec.get("nome_parlamentar_emenda_plano_acao", "")
        nome_beneficiario = rec.get("nome_beneficiario_plano_acao", "")
        valor_inv = rec.get("valor_investimento_plano_acao", 0.0) or 0.0
        valor_cus = rec.get("valor_custeio_plano_acao", 0.0) or 0.0
        valor = valor_inv + valor_cus
        descricao_areas = rec.get("codigo_descricao_areas_politicas_publicas_plano_acao", "")

        if valor <= 0 or not nome_parlamentar:
            continue

        # Resolver município
        nome_munic = re.sub(
            r"^(MUNICIPIO|MUNICÍPIO|PREFEITURA MUNICIPAL|PREFEITURA|CÂMARA MUNICIPAL|CAMARA MUNICIPAL)\s+(DE|DO|DA|DOS|DAS)?\s*",
            "", nome_beneficiario.upper(),
        ).strip()
        nome_munic = re.sub(r"^(DE|DO|DA|DOS|DAS)\s+", "", nome_munic).strip()
        nome_norm = normalizar_nome(nome_munic)

        cod_ibge = por_nome_lookup.get(nome_norm)
        if not cod_ibge:
            for lk, lc in por_nome_lookup.items():
                if nome_norm == lk or (len(nome_norm) > 4 and (lk.startswith(nome_norm) or nome_norm.startswith(lk))):
                    cod_ibge = lc
                    break

        if not cod_ibge:
            nao_resolvidos += 1
            continue

        area = extrair_area(str(descricao_areas))
        em = emendas_por_munic[cod_ibge]
        em["empenhado"] += valor
        em["n"] += 1
        em["parl"].add(nome_parlamentar)
        em["areas"][area] += valor

    print(f"Municípios com emendas no TransfereGov: {len(emendas_por_munic)}")
    print(f"Não resolvidos (sem municipio SC): {nao_resolvidos}")

    # Atualizar estado_sc.json
    atualizados = 0
    for cod_ibge, em_data in emendas_por_munic.items():
        idx = por_id.get(cod_ibge)
        if idx is None:
            nome_norm = normalizar_nome(por_ibge.get(cod_ibge, ""))
            idx = por_nome.get(nome_norm)
        if idx is None:
            continue

        estado[idx]["emendas"] = {
            "empenhado": round(em_data["empenhado"], 2),
            "pago": 0,
            "n": em_data["n"],
            "parl": sorted(em_data["parl"]),
            "areas": [
                {"area": area, "valor": round(val, 2)}
                for area, val in sorted(em_data["areas"].items(), key=lambda x: -x[1])
            ],
        }
        atualizados += 1

    print(f"Municípios atualizados: {atualizados}")

    # Validação SMO
    smo_idx = por_id.get("4217204")
    if smo_idx is not None:
        smo = estado[smo_idx]
        em = smo.get("emendas")
        print(f"\n  === VALIDAÇÃO: São Miguel do Oeste ===")
        if em:
            print(f"  Empenhado: R$ {em['empenhado']:,.2f}")
            print(f"  Parlamentares ({len(em['parl'])}): {em['parl'][:5]}")
            print("  ✅ SMO tem emendas no estado_sc.json!")
        else:
            print("  ⚠️  SMO ainda sem emendas")

    # Salvar
    with open(estado_path, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    size_kb = estado_path.stat().st_size / 1024
    print(f"\n✅ estado_sc.json atualizado: {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
