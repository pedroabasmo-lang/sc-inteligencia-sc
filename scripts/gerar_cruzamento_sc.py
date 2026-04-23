"""
Gerador do cruzamento_sc.json — versão com emendas reais do TransfereGov.

Fonte principal de emendas: raw/transferegov/plano_acao_sc.json
  → campo nome_parlamentar_emenda_plano_acao (nome do deputado)
  → campo nome_beneficiario_plano_acao (nome do município)
  → campo valor_investimento_plano_acao + valor_custeio_plano_acao
  → campo ano_plano_acao

Mapeia CNPJ do beneficiário → cod_ibge via lookups/municipios_br.csv
Usa fuzzy matching por nome quando CNPJ não resolve.

Saída: painel-wilson-sc/cruzamento_sc.json (atualiza o existente)
"""

import json
import re
import gzip
import csv
import unicodedata
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).parent.parent
RAW = BASE / "raw"
LOOKUPS = BASE / "lookups"
PAINEL = BASE.parent / "painel-wilson-sc"

# ── Aliases TSE → chave canônica ──────────────────────────────────────────────
# Mapeamento de NM_URNA_CANDIDATO do TSE para chave usada no cruzamento
ALIASES_TSE = {
    "CAROL DE TONI": "CAROLINE_DE_TONI",
    "CAROLINE DE TONI": "CAROLINE_DE_TONI",
    "PROFESSOR PEDRO UCZAI": "PEDRO_UCZAI",
    "PEDRO UCZAI": "PEDRO_UCZAI",
    "RAFAEL PEZENTI": "PEZENTI",
    "PEZENTI": "PEZENTI",
    "EMANUELZINHO": "EMANUELZINHO",
    "ANA PAULA LIMA": "ANA_PAULA_LIMA",
    "CARLOS CHIODINI": "CARLOS_CHIODINI",
    "CARMEN ZANOTTO": "CARMEN_ZANOTTO",
    "COBALCHINI": "COBALCHINI",
    "CORONEL ARMANDO": "CORONEL_ARMANDO",
    "DANIEL FREITAS": "DANIEL_FREITAS",
    "DANIELA REINEHR": "DANIELA_REINEHR",
    "DARCI DE MATOS": "DARCI_DE_MATOS",
    "FABIO SCHIOCHET": "FABIO_SCHIOCHET",
    "GEOVANIA DE SA": "GEOVANIA_DE_SA",
    "GILSON MARQUES": "GILSON_MARQUES",
    "ISMAEL": "ISMAEL",
    "JORGE GOETTEN": "JORGE_GOETTEN",
    "JULIA ZANATTA": "JULIA_ZANATTA",
    "LUIZ FERNANDO VAMPIRO": "VAMPIRO",
    "VAMPIRO": "VAMPIRO",
    "PEZENTI": "PEZENTI",
    "RICARDO GUIDI": "RICARDO_GUIDI",
    "ZE TROVAO": "ZE_TROVAO",
    "ZÉ TROVÃO": "ZE_TROVAO",
}

# Mapeamento nome parlamentar TransfereGov → chave canônica
ALIASES_TRANSFEREGOV = {
    "Pedro Uczai": "PEDRO_UCZAI",
    "Ana Paula Lima": "ANA_PAULA_LIMA",
    "Carlos Chiodini": "CARLOS_CHIODINI",
    "Carmen Zanotto": "CARMEN_ZANOTTO",
    "Caroline de Toni": "CAROLINE_DE_TONI",
    "Cobalchini": "COBALCHINI",
    "Coronel Armando": "CORONEL_ARMANDO",
    "Daniel Freitas": "DANIEL_FREITAS",
    "Daniela Reinehr": "DANIELA_REINEHR",
    "Darci de Matos": "DARCI_DE_MATOS",
    "Fabio Schiochet": "FABIO_SCHIOCHET",
    "Fábio Schiochet": "FABIO_SCHIOCHET",
    "Geovania de Sá": "GEOVANIA_DE_SA",
    "Geovania De Sá": "GEOVANIA_DE_SA",
    "Geovânia de Sá": "GEOVANIA_DE_SA",
    "Geovânia De Sá": "GEOVANIA_DE_SA",
    "Geovânia de Sá": "GEOVANIA_DE_SA",
    "Gilson Marques": "GILSON_MARQUES",
    "Ismael": "ISMAEL",
    "Jorge Goetten": "JORGE_GOETTEN",
    "Julia Zanatta": "JULIA_ZANATTA",
    "Júlia Zanatta": "JULIA_ZANATTA",
    "Luiz Fernando Vampiro": "VAMPIRO",
    "Vampiro": "VAMPIRO",
    "Pezenti": "PEZENTI",
    "Rafael Pezenti": "PEZENTI",
    "Ricardo Guidi": "RICARDO_GUIDI",
    "Zé Trovão": "ZE_TROVAO",
    "Ze Trovao": "ZE_TROVAO",
    "Carla Ayres": "CARLA_AYRES",
    "Julia Zanatta": "JULIA_ZANATTA",
}


def normalizar_nome(nome: str) -> str:
    """Remove acentos, converte para upper, remove chars especiais."""
    # Tratar casos especiais primeiro: D'OESTE → DO OESTE
    nome = re.sub(r"D'OESTE", "DO OESTE", nome.upper())
    nome = re.sub(r"D'OESTE", "DO OESTE", nome)  # sem upper para capturar variações
    s = unicodedata.normalize("NFD", nome)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z0-9 ]", "", s.upper())
    return re.sub(r"\s+", " ", s).strip()


def nome_para_chave(nome: str) -> str:
    """Converte nome de município para chave lookup."""
    return normalizar_nome(nome).replace(" ", "_")


def carregar_lookup_municipios() -> dict:
    """Retorna dict: nome_normalizado → cod_ibge, e cod_ibge → dict."""
    por_nome = {}
    por_ibge = {}
    with open(LOOKUPS / "municipios_br.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("uf", "").upper() != "SC":
                continue
            cod = row["cod_ibge"]
            nome_norm = row["nome_normalizado"]
            por_nome[nome_norm] = cod
            por_ibge[cod] = {
                "cod_ibge": cod,
                "nome": row["nome"],
                "nome_normalizado": nome_norm,
                "uf": "SC",
                "mesorregiao": row.get("mesorregiao", ""),
                "microrregiao": row.get("microrregiao", ""),
            }
    print(f"  Lookup: {len(por_nome)} municípios SC")
    return por_nome, por_ibge


def carregar_transferegov_emendas(por_nome_lookup: dict) -> dict:
    """
    Lê raw/transferegov/plano_acao_sc.json e agrega emendas por:
      municipio_ibge → parlamentar_chave → {total, count, anos}
    
    Usa: plano_acao_sc.json (3601 registros incluindo todos dep SC)
    """
    emendas_path = RAW / "transferegov" / "plano_acao_sc.json"
    d = json.load(open(emendas_path, encoding="utf-8"))
    records = d.get("data", [])
    print(f"  TransfereGov: {len(records)} registros brutos")

    # Estrutura: cod_ibge → chave_dep → {total, count, anos: set}
    resultado = defaultdict(lambda: defaultdict(lambda: {"total": 0.0, "count": 0, "anos": set()}))
    nao_resolvidos = 0
    resolvidos = 0

    for rec in records:
        nome_parlamentar = rec.get("nome_parlamentar_emenda_plano_acao", "")
        nome_beneficiario = rec.get("nome_beneficiario_plano_acao", "")
        valor_inv = rec.get("valor_investimento_plano_acao", 0.0) or 0.0
        valor_cus = rec.get("valor_custeio_plano_acao", 0.0) or 0.0
        valor = valor_inv + valor_cus
        ano = str(rec.get("ano_plano_acao", ""))

        if valor <= 0:
            continue

        # Resolver parlamentar
        chave_dep = ALIASES_TRANSFEREGOV.get(nome_parlamentar)
        if not chave_dep:
            # Tentativa fuzzy
            nome_norm = normalizar_nome(nome_parlamentar)
            for alias_key, alias_chave in ALIASES_TRANSFEREGOV.items():
                if normalizar_nome(alias_key) in nome_norm or nome_norm in normalizar_nome(alias_key):
                    chave_dep = alias_chave
                    break
        
        if not chave_dep:
            continue  # Pula parlamentares de outros estados

        # Resolver município → cod_ibge
        # Remove prefixo "MUNICIPIO DE ", "MUNICÍPIO DE ", etc.
        nome_munic = re.sub(
            r"^(MUNICIPIO|MUNICÍPIO|PREFEITURA MUNICIPAL|PREFEITURA|CÂMARA MUNICIPAL|CAMARA MUNICIPAL)\s+(DE|DO|DA|DOS|DAS)?\s*",
            "",
            nome_beneficiario.upper(),
        ).strip()
        nome_munic = re.sub(r"^(DE|DO|DA|DOS|DAS)\s+", "", nome_munic).strip()
        nome_norm = normalizar_nome(nome_munic)

        cod_ibge = por_nome_lookup.get(nome_norm)
        if not cod_ibge:
            # Tentativa parcial: verifica se algum nome começa com o nome normalizado
            for lk_nome, lk_cod in por_nome_lookup.items():
                if nome_norm == lk_nome or (len(nome_norm) > 4 and (lk_nome.startswith(nome_norm) or nome_norm.startswith(lk_nome))):
                    cod_ibge = lk_cod
                    break

        if not cod_ibge:
            nao_resolvidos += 1
            continue

        resultado[cod_ibge][chave_dep]["total"] += valor
        resultado[cod_ibge][chave_dep]["count"] += 1
        resultado[cod_ibge][chave_dep]["anos"].add(ano)
        resolvidos += 1

    print(f"  TransfereGov resolvidos: {resolvidos} | não resolvidos (outros estados/entidades): {nao_resolvidos}")

    # Converter sets para listas
    for cod in resultado:
        for dep in resultado[cod]:
            resultado[cod][dep]["anos"] = sorted(resultado[cod][dep]["anos"])

    return dict(resultado)


def carregar_tse_votos() -> dict:
    """
    Lê raw/tse/votacao_dep_federal_sc_2022.csv.gz
    Retorna: cod_ibge_tse → deputado_chave → total_votos
    
    Nota: CD_MUNICIPIO do TSE ≠ cod_ibge IBGE.
    Usa NM_MUNICIPIO para match com lookup.
    """
    votos_path = RAW / "tse" / "votacao_dep_federal_sc_2022.csv.gz"
    
    # Acumula: nome_municipio_tse → candidato_urna → votos
    por_municipio = defaultdict(lambda: defaultdict(int))
    
    with gzip.open(votos_path, "rt", encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row.get("DS_CARGO", "") != "Deputado Federal":
                continue
            if row.get("NR_TURNO", "") != "1":
                continue
            
            nm_munic = row.get("NM_MUNICIPIO", "").strip()
            nm_urna = row.get("NM_URNA_CANDIDATO", "").strip()
            try:
                votos = int(row.get("QT_VOTOS_NOMINAIS", 0) or 0)
            except (ValueError, TypeError):
                votos = 0
            
            if not nm_munic or not nm_urna or votos <= 0:
                continue
            
            chave_dep = ALIASES_TSE.get(nm_urna.upper())
            if not chave_dep:
                # Tentativa: normaliza e tenta match
                nome_norm = normalizar_nome(nm_urna)
                for alias, chave in ALIASES_TSE.items():
                    if normalizar_nome(alias) == nome_norm:
                        chave_dep = chave
                        break
            
            if chave_dep:
                por_municipio[normalizar_nome(nm_munic)][chave_dep] += votos

    print(f"  TSE: {len(por_municipio)} municípios com votos")
    return dict(por_municipio)


def carregar_stn_fpm() -> dict:
    """
    Lê raw/stn/fpm_sc_2024.json
    Retorna: nome_normalizado → total_fpm_2024
    """
    fpm_path = RAW / "stn" / "fpm_sc_2024.json"
    d = json.load(open(fpm_path, encoding="utf-8"))
    data = d.get("data_por_municipio", [])
    
    resultado = {}
    for item in data:
        nome = normalizar_nome(item.get("municipio", ""))
        total = item.get("total_2024", 0.0) or 0.0
        resultado[nome] = total
    
    print(f"  STN FPM: {len(resultado)} municípios")
    return resultado


def carregar_senadores() -> list:
    """Carrega senadores SC do raw/senado/"""
    senadores_path = RAW / "senado"
    if not senadores_path.exists():
        return []
    
    senadores = []
    for f in senadores_path.glob("*.json"):
        try:
            d = json.load(open(f, encoding="utf-8"))
            if isinstance(d, list):
                senadores.extend(d)
            elif isinstance(d, dict):
                dados = d.get("data", d.get("dados", []))
                if dados:
                    senadores.extend(dados if isinstance(dados, list) else [dados])
        except Exception:
            pass
    
    print(f"  Senadores SC: {len(senadores)} registros encontrados")
    return senadores


def main():
    print("=== Gerador cruzamento_sc.json com emendas reais ===\n")

    # 1. Carregar lookup de municípios
    print("[1/6] Carregando lookup de municípios SC...")
    por_nome_lookup, por_ibge = carregar_lookup_municipios()

    # 2. Carregar emendas TransfereGov
    print("[2/6] Processando emendas TransfereGov...")
    emendas_por_municipio = carregar_transferegov_emendas(por_nome_lookup)
    print(f"  Municípios com emendas: {len(emendas_por_municipio)}")

    # 3. Carregar votos TSE
    print("[3/6] Processando votos TSE 2022...")
    votos_tse = carregar_tse_votos()

    # 4. Carregar FPM
    print("[4/6] Processando FPM STN 2024...")
    fpm_por_municipio = carregar_stn_fpm()

    # 5. Carregar cruzamento existente (preserva campos de prefeito, partido_pref etc.)
    print("[5/6] Carregando cruzamento_sc.json existente...")
    cruzamento_atual = json.load(open(PAINEL / "cruzamento_sc.json", encoding="utf-8"))
    
    # Indexar municípios existentes por id
    munics_por_id = {str(m["id"]): m for m in cruzamento_atual.get("municipios", [])}
    munics_por_nome = {normalizar_nome(m["nome"]): m for m in cruzamento_atual.get("municipios", [])}
    
    deps_existentes = cruzamento_atual.get("deps", [])
    print(f"  Deps existentes: {len(deps_existentes)}")

    # 6. Calcular totais por deputado e gerar novo cruzamento
    print("[6/6] Gerando cruzamento atualizado...")
    
    # Calcular total de emendas por deputado
    total_emendas_dep = defaultdict(float)
    for cod_ibge, deps_emendas in emendas_por_municipio.items():
        for chave_dep, info in deps_emendas.items():
            total_emendas_dep[chave_dep] += info["total"]

    print("\n  Emendas por deputado (TransfereGov):")
    for dep, total in sorted(total_emendas_dep.items(), key=lambda x: -x[1]):
        print(f"    {dep}: R$ {total:,.0f}")

    # Atualizar lista de deps com total_emendas
    deps_atualizados = []
    for dep in deps_existentes:
        chave = dep.get("chave", "")
        dep_updated = dict(dep)
        dep_updated["total_emendas"] = round(total_emendas_dep.get(chave, 0.0), 2)
        deps_atualizados.append(dep_updated)

    # Atualizar municípios com emendas reais + FPM + votos completos
    municipios_atualizados = []
    munic_com_emendas = 0
    
    for cod_ibge, info_ibge in por_ibge.items():
        munic_existente = munics_por_id.get(cod_ibge) or munics_por_nome.get(info_ibge["nome_normalizado"])
        
        # Emendas por deputado neste município
        emendas_munic = emendas_por_municipio.get(cod_ibge, {})
        
        # Emendas: dict chave_dep → total
        emendas_dict = {dep: round(info["total"], 2) for dep, info in emendas_munic.items()}
        total_emendas_munic = round(sum(emendas_dict.values()), 2)
        
        if total_emendas_munic > 0:
            munic_com_emendas += 1

        # Votos TSE
        nome_norm = info_ibge["nome_normalizado"]
        votos_munic = votos_tse.get(nome_norm, {})

        # FPM
        fpm = fpm_por_municipio.get(nome_norm, 0.0)

        munic_novo = {
            "id": int(cod_ibge),
            "nome": info_ibge["nome"],
            "uf": "SC",
            "mesorregiao": info_ibge.get("mesorregiao", ""),
            "microrregiao": info_ibge.get("microrregiao", ""),
        }

        # Preservar campos do existente (prefeito, partido_pref)
        if munic_existente:
            for campo in ["prefeito", "partido_pref"]:
                if campo in munic_existente:
                    munic_novo[campo] = munic_existente[campo]

        # Votos
        if votos_munic:
            munic_novo["tv"] = sum(votos_munic.values())
            munic_novo["v"] = {k: v for k, v in sorted(votos_munic.items())}
        elif munic_existente and "v" in munic_existente:
            munic_novo["tv"] = munic_existente.get("tv", 0)
            munic_novo["v"] = munic_existente["v"]

        # FPM
        if fpm > 0:
            munic_novo["fpm_2024"] = round(fpm, 2)

        # Emendas — campo 'e' é o que o painel index.html usa (m.e)
        if emendas_dict:
            munic_novo["e"] = emendas_dict
            munic_novo["total_emendas"] = total_emendas_munic

        municipios_atualizados.append(munic_novo)

    # Ordenar por nome
    municipios_atualizados.sort(key=lambda m: m["nome"])

    print(f"\n  Municípios com emendas reais: {munic_com_emendas} / {len(municipios_atualizados)}")

    # Montar JSON final
    cruzamento_novo = {
        "uf": "SC",
        "gerado_em": "2026-04-22",
        "fonte_emendas": "TransfereGov — plano_acao_especial",
        "fonte_votos": "TSE — votacao_dep_federal_sc_2022",
        "fonte_fpm": "STN — FPM 2024",
        "deps": deps_atualizados,
        "municipios": municipios_atualizados,
    }

    # Salvar
    output_path = PAINEL / "cruzamento_sc.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cruzamento_novo, f, ensure_ascii=False, indent=2)

    size_kb = output_path.stat().st_size / 1024
    print(f"\n✅ cruzamento_sc.json gerado: {output_path}")
    print(f"   Tamanho: {size_kb:.1f} KB")
    print(f"   Deps: {len(deps_atualizados)}")
    print(f"   Municípios: {len(municipios_atualizados)}")
    print(f"   Municípios com emendas: {munic_com_emendas}")

    # Validação: São Miguel do Oeste
    smo = [m for m in municipios_atualizados if str(m["id"]) == "4217204"]
    if smo:
        print(f"\n  === VALIDAÇÃO: São Miguel do Oeste ===")
        emendas_smo = smo[0].get("e", {})  # campo 'e' é o que o painel usa
        uczai_smo = emendas_smo.get("PEDRO_UCZAI", 0)
        total_smo = smo[0].get("total_emendas", 0)
        print(f"  Pedro Uczai emendas: R$ {uczai_smo:,.2f}")
        print(f"  Total emendas no município: R$ {total_smo:,.2f}")
        if uczai_smo > 0:
            print("  ✅ PEDRO UCZAI APARECE COM EMENDAS — BUG CORRIGIDO!")
        else:
            print("  ⚠️  Pedro Uczai ainda aparece com R$0 em São Miguel do Oeste")
            # Debug: verificar se há registros de SMO no transferegov
            print(f"     Emendas disponíveis para SMO: {emendas_smo}")
    
    # Validação: Pedro Uczai total
    uczai_dep = [d for d in deps_atualizados if d.get("chave") == "PEDRO_UCZAI"]
    if uczai_dep:
        print(f"\n  Pedro Uczai total emendas: R$ {uczai_dep[0].get('total_emendas', 0):,.2f}")


if __name__ == "__main__":
    main()
