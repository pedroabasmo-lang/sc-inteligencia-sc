#!/usr/bin/env python3
"""
Compilar resultados finais com todos os dados coletados e registros de diagnóstico
"""

import json
import time
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch(url, params=None, method="GET", verify=False, timeout=20, headers=None):
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, */*"}
    if headers:
        h.update(headers)
    try:
        if method == "GET":
            resp = requests.get(url, params=params, headers=h, verify=verify, timeout=timeout, allow_redirects=True)
        else:
            resp = requests.post(url, data=params, headers=h, verify=verify, timeout=timeout)
        ct = resp.headers.get("Content-Type", "")
        preview = resp.text[:500]
        is_json = False
        data = None
        if "json" in ct.lower():
            try:
                data = resp.json()
                is_json = True
            except:
                pass
        elif resp.text.strip().startswith(("{", "[")):
            try:
                data = resp.json()
                is_json = True
            except:
                pass
        return {
            "status_http": resp.status_code,
            "content_type": ct,
            "primeiros_500_chars": preview,
            "json_disponivel": is_json,
            "dados": data,
            "erro": None,
        }
    except Exception as e:
        return {
            "status_http": None,
            "content_type": None,
            "primeiros_500_chars": None,
            "json_disponivel": False,
            "dados": {"status": "erro_conexao", "detalhe": str(e)},
            "erro": str(e),
        }

# ============================================================
# FNDE SIGEF - dados confirmados funcionando
# ============================================================
print("=== Coletando dados FNDE SIGEF municipios SC ===")
sigef_municipios = fetch(
    "https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax/estado/SC",
)
time.sleep(0.5)

sigef_programas_2024 = fetch(
    "https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax/ano/2024",
)
time.sleep(0.5)

sigef_programas_2023 = fetch(
    "https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax/ano/2023",
)
time.sleep(0.5)

# ============================================================
# TAREFA 3 — FNDE PNAE SC (resultado final)
# ============================================================
print("\n=== TAREFA 3: FNDE PNAE SC ===")

# From SIGEF: PNAE program ID = C7, PDDE = 02
# The SIGEF AJAX returns programs/municipalities lists (reference data)
# Actual financial data requires CAPTCHA on the main form

# Try FNDE PDDE INFO system (public)
pdde_info = fetch(
    "https://www.gov.br/fnde/pt-br/assuntos/sistemas/pddeinfo",
    verify=True,
)
time.sleep(0.5)

# Try FNDE external API  
pnae_tests = []

test_urls_pnae = [
    ("https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax/ano/2024", None, "SIGEF AJAX programas 2024"),
    ("https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax/estado/SC", None, "SIGEF AJAX municipios SC"),
    ("https://www.fnde.gov.br/sigpcadm/api/v1/repasses", {"programa": "PNAE", "uf": "SC", "ano": "2024"}, "SIGPC API (WAF bloqueado)"),
    ("https://www.gov.br/fnde/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-1", None, "FNDE dados-abertos-1"),
]

for url, params, label in test_urls_pnae:
    r = fetch(url, params=params, verify=False)
    r["url"] = url
    r["label"] = label
    pnae_tests.append(r)
    print(f"  [{r['status_http']}] {label}")
    time.sleep(0.5)

# ============================================================
# TAREFA 4 — FNDE PDDE SC (resultado final)  
# ============================================================
print("\n=== TAREFA 4: FNDE PDDE SC ===")

pdde_tests = []
test_urls_pdde = [
    ("https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax/ano/2024", None, "SIGEF AJAX programas 2024 (inclui PDDE ID=02)"),
    ("https://www.gov.br/fnde/pt-br/assuntos/sistemas/pddeinfo", None, "PDDE INFO sistema"),
    ("https://www.gov.br/fnde/pt-br/assuntos/sistemas/pddeweb", None, "PDDE WEB sistema"),
]

for url, params, label in test_urls_pdde:
    r = fetch(url, params=params, verify=True, timeout=15)
    r["url"] = url
    r["label"] = label
    pdde_tests.append(r)
    print(f"  [{r['status_http']}] {label}")
    time.sleep(0.5)

# ============================================================
# Compilar PNAE resultado final
# ============================================================
pnae_resultado = {
    "coletado_em": datetime.now().isoformat(),
    "fonte": "https://www.fnde.gov.br/sigefweb/index.php/liberacoes",
    "tarefa": "FNDE PNAE SC",
    "status": "dados_referencia_coletados",
    "nota": (
        "Os endpoints primários (sigpcadm API, dadosabertos.fnde.gov.br) retornaram erro WAF ou DNS não resolveu. "
        "O SIGEF (Sistema Integrado de Gestão Financeira) do FNDE retorna dados de referência via AJAX "
        "mas os dados financeiros requerem reCAPTCHA v2 para acesso. "
        "Foram coletados: lista de municípios SC com IDs, lista de programas disponíveis (incluindo PNAE ID=C7). "
        "Para coleta dos valores de repasse, é necessário reCAPTCHA bypass ou acesso ao SIGEF com sessão autenticada."
    ),
    "endpoints_testados": pnae_tests,
    "dados_referencia": {
        "programa_pnae": {
            "id": "C7",
            "nome": "ALIMENTAÇÃO ESCOLAR (PROG.NACIONAL DE ALIMENTAÇÃO ESCOLAR)",
            "ds_programa_fnde": "ALIMENTAÇÃO ESCOLAR",
            "fonte": "https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax/ano/2024"
        },
        "municipios_sc": sigef_municipios.get("dados", []) if sigef_municipios.get("json_disponivel") else [],
        "programas_disponiveis_2024": sigef_programas_2024.get("dados", []) if sigef_programas_2024.get("json_disponivel") else [],
    },
    "status_http_sigef_ajax": sigef_municipios.get("status_http"),
}

with open("/home/user/workspace/sc-inteligencia/raw/fnde/pnae_sc.json", "w", encoding="utf-8") as f:
    json.dump(pnae_resultado, f, ensure_ascii=False, indent=2, default=str)
print(f"\n[SAVED] pnae_sc.json ({len(pnae_resultado.get('dados_referencia', {}).get('municipios_sc', []))} municípios SC)")

# ============================================================
# Compilar PDDE resultado final
# ============================================================
pdde_resultado = {
    "coletado_em": datetime.now().isoformat(),
    "fonte": "https://www.fnde.gov.br/sigefweb/index.php/liberacoes",
    "tarefa": "FNDE PDDE SC",
    "status": "dados_referencia_coletados",
    "nota": (
        "dadosabertos.fnde.gov.br DNS não resolveu. "
        "O SIGEF retorna lista de programas disponíveis (PDDE ID=02, PDDE EQUIDADE ID=0A, PDDE QUALIDADE ID=0B) "
        "via AJAX mas os dados financeiros requerem reCAPTCHA. "
        "Sistemas PDDE INFO e PDDEWeb estão disponíveis mas requerem navegação web interativa."
    ),
    "endpoints_testados": pdde_tests,
    "dados_referencia": {
        "programas_pdde": [
            {"id": "02", "nome": "PDDE (PROGRAMA DINHEIRO DIRETO NA ESCOLA)", "ds": "PDDE"},
            {"id": "0A", "nome": "PDDE EQUIDADE (ÁGUA E ESGOTAMENTO SANITÁRIO, ESCOLA DO CAMPO, ESCOLA ACESSÍVEL E PDE ESCOLA)", "ds": "PDDE EQUIDADE"},
            {"id": "0B", "nome": "PDDE QUALIDADE (ENSINO MÉDIO INOVADOR, MAIS CULTURA, ESC.DE FRONTEIRA, ATLETA NA ESCOLA, ESC.SUSTENTÁVEL)", "ds": "PDDE QUALIDADE"},
            {"id": "A3", "nome": "PDDE-EDUCAÇÃO ESPECIAL (PROGRAMA DINHEIRO DIRETO NA ESCOLA-EDUCAÇÃO ESPECIAL)", "ds": "PDDE-EDUCAÇÃO ESPECIAL"},
        ],
        "municipios_sc": sigef_municipios.get("dados", []) if sigef_municipios.get("json_disponivel") else [],
        "fonte_referencia": "https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax/ano/2024",
    },
}

with open("/home/user/workspace/sc-inteligencia/raw/fnde/pdde_sc.json", "w", encoding="utf-8") as f:
    json.dump(pdde_resultado, f, ensure_ascii=False, indent=2, default=str)
print(f"[SAVED] pdde_sc.json")

# ============================================================
# Atualizar FNS repasses com diagnóstico completo
# ============================================================
print("\n=== Atualizando FNS repasses com diagnóstico ===")

# FNS apifns.saude.gov.br does not resolve (internal/VPN only)
# FNS portal is at portalfns.saude.gov.br (WordPress)
# The FNS SIGEF equivalent would be SIOPS or direct API
# Test portalfns WP API for any financial data

portafns_test = fetch("https://portalfns.saude.gov.br/wp-json/wp/v2/posts?per_page=5&categories=repasse", verify=False)
time.sleep(0.5)

fns_repasses_resultado = {
    "coletado_em": datetime.now().isoformat(),
    "tarefa": "FNS repasses SC 2023-2024",
    "endpoints_testados": [
        {
            "label": "Opção A - apifns.saude.gov.br/v1/gestor/repasses",
            "url": "https://apifns.saude.gov.br/v1/gestor/repasses",
            "params": {"uf": "SC", "competencia": "202401"},
            "status_http": None,
            "primeiros_500_chars": None,
            "dados": {"status": "erro_conexao", "detalhe": "DNS não resolve: apifns.saude.gov.br (acesso restrito/VPN interna)"},
            "erro": "NameResolutionError: apifns.saude.gov.br não tem entrada DNS pública",
        },
        {
            "label": "Opção B - apifns.saude.gov.br/v1/repasses",
            "url": "https://apifns.saude.gov.br/v1/repasses",
            "params": {"uf": "SC", "ano": "2024"},
            "status_http": None,
            "primeiros_500_chars": None,
            "dados": {"status": "erro_conexao", "detalhe": "DNS não resolve: mesmo host que Opção A"},
            "erro": "NameResolutionError: mesmo domínio que Opção A",
        },
        {
            "label": "Opção C - fns.saude.gov.br portal web",
            "url": "https://www.fns.saude.gov.br/visao/consultarTransferenciaFundo.action",
            "params": {"uf": "SC"},
            "status_http": 404,
            "primeiros_500_chars": "Redirected to portalfns.saude.gov.br - URL /visao/consultarTransferenciaFundo.action não existe mais",
            "dados": {"status": "html_retornado", "endpoint_nao_disponivel": True, "nota": "Portal migrado para portalfns.saude.gov.br (WordPress)"},
            "erro": None,
        },
    ],
    "diagnostico": {
        "apifns_saude_gov_br": "Não tem entrada DNS pública — provavelmente acessível apenas via rede interna do MS ou VPN",
        "fns_saude_gov_br": "Redirecionado para portalfns.saude.gov.br (site WordPress institucional, sem dados abertos em API)",
        "portal_fns": "portalfns.saude.gov.br está ativo mas é site institucional (posts/pages, sem endpoint de dados financeiros)",
        "alternativa_sugerida": "Portal da Transparência Federal via https://portaldatransparencia.gov.br (requer chave API cadastrada em portaldatransparencia.gov.br/api-de-dados/cadastrar-email)",
    },
    "dados": {"status": "endpoint_nao_disponivel_publicamente", "endpoint_nao_disponivel": True},
    "competencias_solicitadas": {
        "2023": [f"2023{str(m).zfill(2)}" for m in range(1, 13)],
        "2024": [f"2024{str(m).zfill(2)}" for m in range(1, 4)],
    },
}

with open("/home/user/workspace/sc-inteligencia/raw/fns/repasses_sc.json", "w", encoding="utf-8") as f:
    json.dump(fns_repasses_resultado, f, ensure_ascii=False, indent=2, default=str)
print("[SAVED] repasses_sc.json")

# ============================================================
# Atualizar FNS emenda
# ============================================================
print("\n=== Atualizando FNS emenda ===")

fns_emenda_resultado = {
    "coletado_em": datetime.now().isoformat(),
    "tarefa": "FNS emenda 202428550022",
    "endpoints_testados": [
        {
            "label": "apifns.saude.gov.br/v1/gestor/emenda",
            "url": "https://apifns.saude.gov.br/v1/gestor/emenda",
            "params": {"numero": "202428550022"},
            "status_http": None,
            "primeiros_500_chars": None,
            "dados": {"status": "erro_conexao", "detalhe": "DNS não resolve: apifns.saude.gov.br (acesso restrito/VPN interna)"},
            "erro": "NameResolutionError: apifns.saude.gov.br não tem entrada DNS pública",
        }
    ],
    "diagnostico": {
        "apifns_saude_gov_br": "Não tem entrada DNS pública — acesso apenas via rede interna do Ministério da Saúde ou VPN",
        "numero_emenda": "202428550022",
        "alternativa": "Consultar via Portal da Transparência: https://portaldatransparencia.gov.br/emendas/consulta"
    },
    "dados": {"status": "endpoint_nao_disponivel_publicamente", "endpoint_nao_disponivel": True},
}

with open("/home/user/workspace/sc-inteligencia/raw/fns/emenda_uczai_teste.json", "w", encoding="utf-8") as f:
    json.dump(fns_emenda_resultado, f, ensure_ascii=False, indent=2, default=str)
print("[SAVED] emenda_uczai_teste.json")

# ============================================================
# Salvar metadados de diagnóstico geral
# ============================================================
print("\n=== Salvando metadados gerais ===")

metadados = {
    "coletado_em": datetime.now().isoformat(),
    "executor": "coleta_fns_fnde.py + compilar_resultados.py",
    "resumo_endpoints": {
        "fns": {
            "apifns.saude.gov.br": {
                "dns_resolve": False,
                "status": "acesso_apenas_rede_interna",
                "endpoints_testados": [
                    "https://apifns.saude.gov.br/v1/gestor/repasses",
                    "https://apifns.saude.gov.br/v1/repasses",
                    "https://apifns.saude.gov.br/v1/gestor/emenda",
                ],
            },
            "portalfns.saude.gov.br": {
                "dns_resolve": True,
                "ip": "189.9.35.156",
                "status": "site_wordpress_institucional",
                "nota": "Sem endpoint de dados financeiros",
            },
            "fns.saude.gov.br": {
                "dns_resolve": True,
                "status": "redireciona_para_portalfns",
                "url_consultarTransferenciaFundo": "404 - URL não existe mais",
            },
        },
        "fnde": {
            "dadosabertos.fnde.gov.br": {
                "dns_resolve": False,
                "status": "DNS_NXDOMAIN",
                "nota": "Domínio sem entrada DNS pública",
            },
            "www.fnde.gov.br": {
                "dns_resolve": True,
                "status": "disponivel",
                "sigpcadm_api": "bloqueado_waf_http_200_html_error",
                "sigefweb_ajax": "funcionando",
                "sigefweb_liberacoes": "requer_recaptcha_para_dados_financeiros",
            },
            "olinda.fnde.gov.br": {
                "dns_resolve": False,
                "status": "DNS_sem_resposta",
            },
        },
        "alternativas": {
            "portal_transparencia": {
                "url": "https://api.portaldatransparencia.gov.br/api-de-dados/",
                "status": "requer_chave_api",
                "cadastro": "https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email",
                "endpoints_relevantes": [
                    "transferencias-fundo-a-fundo",
                    "transferencias-financeiras",
                    "emendas-individuais",
                ],
            },
            "sigef_ajax_dados_referencia": {
                "url": "https://www.fnde.gov.br/sigefweb/index.php/liberacoes/ajax",
                "status": "funcionando",
                "dados_disponiveis": [
                    "lista_municipios_sc (295 municípios com IDs)",
                    "lista_programas (PNAE=C7, PDDE=02, PDDE EQUIDADE=0A, etc.)",
                ],
            },
        },
    },
    "arquivos_salvos": [
        "/home/user/workspace/sc-inteligencia/raw/fns/repasses_sc.json",
        "/home/user/workspace/sc-inteligencia/raw/fns/emenda_uczai_teste.json",
        "/home/user/workspace/sc-inteligencia/raw/fnde/pnae_sc.json",
        "/home/user/workspace/sc-inteligencia/raw/fnde/pdde_sc.json",
    ],
}

with open("/home/user/workspace/sc-inteligencia/raw/metadados_coleta.json", "w", encoding="utf-8") as f:
    json.dump(metadados, f, ensure_ascii=False, indent=2, default=str)
print("[SAVED] metadados_coleta.json")

print("\n" + "="*60)
print("COMPILAÇÃO CONCLUÍDA")
print("="*60)

# Verify files
import os
for path in metadados["arquivos_salvos"] + ["/home/user/workspace/sc-inteligencia/raw/metadados_coleta.json"]:
    size = os.path.getsize(path)
    print(f"  {path} ({size:,} bytes)")
