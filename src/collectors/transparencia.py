"""
Coletor Portal da Transparência — Emendas parlamentares.

URL base: https://api.portaldatransparencia.gov.br/api-de-dados
Documentação: https://api.portaldatransparencia.gov.br/swagger-ui.html

Autenticação:
  Header obrigatório: 'chave-api: SUA_CHAVE'
  Sem a chave, todas as requisições retornam HTTP 401.
  Solicitar em: https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email

Endpoints usados:

  GET /emendas
      Descrição: Lista emendas parlamentares com filtros flexíveis.
      Params:
        codigoAutor (int)          — ID do parlamentar no SIOP (≠ ID da Câmara!)
        nomeAutor (str)            — nome do parlamentar (partial match, case insensitive)
        ano (int)                  — ano de exercício orçamentário
        codigoFuncao (int)         — função orçamentária (10=Saúde, 12=Educação, etc.)
        tipoEmenda (str)           — "Emenda Individual", "Emenda de Bancada", "Emenda de Comissão"
        codigoMunicipioIBGE (int)  — código IBGE 7 dígitos do município destino
        numeroEmenda (str)         — número completo da emenda
        pagina (int)               — número da página (default: 1, base 1)
        [sem parâmetro de tamanho]  — fixo em 100 registros por página
      Resposta: lista direta de objetos (sem envelope)

  GET /emendas/{id}
      Descrição: Detalhe de uma emenda específica pelo ID interno do Portal.
      Resposta: objeto único com todos os campos.

Formato de resposta (item de /emendas):
{
  "codigoEmenda": 103828,
  "numeroEmenda": "202428550023",
  "ano": 2024,
  "tipoEmenda": "Emenda Individual",
  "nomeAutor": "PEDRO UCZAI",
  "codigoAutor": 123456,
  "uf": "SANTA CATARINA",
  "codigoMunicipioIBGE": null,           ← NULL quando destino é UF/Múltiplo
  "funcao": "10 - Saúde",
  "subfuncao": "301 - Atenção Básica",
  "objeto": "CONSTRUÇÃO DE UBS",
  "nomeFavorecido": null,
  "cnpjFavorecido": null,
  "valorEmpenhado": 13700000.00,
  "valorLiquidado": 13700000.00,
  "valorPago": 13700000.00,
  "valorRpInscrito": 0.00,
  "tipoResultadoPrimario": "6",          ← "6"=RP6, "7"=RP7, "8"=RP8, "9"=RP9
  "transferenciaEspecial": false,
  "impedimentoTecnico": false
}

CAMPO CRÍTICO: codigoMunicipioIBGE
  - Quando preenchido (int 7 dígitos): emenda vai para município específico
    → usar cod_ibge diretamente, granularidade_perdida=False
  - Quando NULL: emenda vai para UF inteira ou múltiplos municípios
    → granularidade_perdida=True → acionar TransfereGovCollector e/ou FNSCollector

CAMPO uf:
  ATENÇÃO: contém o NOME COMPLETO do estado em maiúsculas
  ("SANTA CATARINA", "RIO GRANDE DO SUL", "SÃO PAULO", etc.)
  NUNCA usar para comparar com siglas (SC, RS, SP).
  Para derivar a sigla, usar o prefixo do codigoMunicipioIBGE via IBGE_UF_PREFIX.

Rate limit:
  Com chave válida: 50 requisições/minuto (aproximadamente 0.83 req/s).
  Semáforo configurado em 3 req/s como buffer extra de segurança.
  Em caso de HTTP 429, o cliente HTTP faz retry com backoff automático.

NOTA SOBRE nomeAutor:
  O campo nomeAutor no Portal da Transparência é o nome registrado no SIOP,
  que pode diferir do nome na API da Câmara:
    API Câmara: "nome" = "Pedro Uczai"  (nome de urna com capitalização)
    Portal:     "nomeAutor" = "PEDRO UCZAI" (maiúsculas, sem acentos às vezes)
  
  Usar partial match e .upper() para robustez no filtro de nome.
"""
import logging
from decimal import Decimal
from typing import Optional

from src.utils.http import APIClient
from src.config import settings

logger = logging.getLogger("sc_inteligencia.collectors.transparencia")

# Prefixo IBGE (2 dígitos) → sigla UF
IBGE_UF_PREFIX: dict[str, str] = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA",
    "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
    "26": "PE", "27": "AL", "28": "SE", "29": "BA",
    "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS",
    "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}

# Mapeamento de tipoResultadoPrimario para tipo RP legível
RP_MAP: dict[str, str] = {
    "6": "RP6_individual",
    "7": "RP7_bancada",
    "8": "RP8_comissao",
    "9": "RP9_relator",
}

# Funções orçamentárias relevantes para saúde e educação
FUNCAO_CODIGOS: dict[str, int] = {
    "saude": 10,
    "educacao": 12,
    "assistencia_social": 8,
    "previdencia": 9,
    "habitacao": 16,
    "saneamento": 17,
    "cultura": 13,
    "transporte": 26,
}


class TransparenciaCollector:
    """
    Coleta emendas parlamentares do Portal da Transparência.

    ATENÇÃO CRÍTICA:
      O campo 'uf' no JSON retornado contém o NOME COMPLETO do estado em
      maiúsculas (ex: "SANTA CATARINA"), NUNCA a sigla.
      Sempre usar _derivar_uf() para obter a sigla a partir do prefixo do
      codigoMunicipioIBGE — é a única fonte confiável da sigla por registro.

    CHAVE DE API:
      Obrigatória. Configurar via variável de ambiente PORTAL_TRANSPARENCIA_API_KEY.
      Sem a chave, todas as chamadas retornam HTTP 401 (não é possível contornar).

    Uso básico:
        async with TransparenciaCollector() as collector:
            emendas = await collector.buscar_emendas_autor("PEDRO UCZAI", 2024)
            mun = await collector.buscar_emendas_municipio(4205407, 2024)
    """

    def __init__(self):
        if not settings.PORTAL_TRANSPARENCIA_API_KEY:
            logger.warning(
                "PORTAL_TRANSPARENCIA_API_KEY não configurada — chamadas retornarão HTTP 401. "
                "Solicitar chave em: https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email"
            )

        self.client = APIClient(
            base_url=settings.TRANSPARENCIA_API,
            headers={"chave-api-dados": settings.PORTAL_TRANSPARENCIA_API_KEY or ""},
            rate_limit=3,  # conservador: 50 req/min ÷ 20s buffer = ~3 req/s
        )

    async def buscar_emendas_autor(
        self,
        nome_autor: str,
        ano: int,
        uf_filtro: Optional[str] = None,
        funcao: Optional[int] = None,
    ) -> list[dict]:
        """
        Busca emendas de um parlamentar por nome e ano.

        Args:
            nome_autor: nome como registrado no Portal da Transparência
                        (ex: "PEDRO UCZAI", "PEDRO UCZAI"). O método converte
                        para maiúsculas automaticamente.
            ano: ano de exercício orçamentário (ex: 2024).
            uf_filtro: se fornecido (ex: "SC"), filtra emendas cujo prefixo
                       do codigoMunicipioIBGE corresponda à UF. NÃO filtra
                       pelo campo 'uf' (nome completo) para evitar erros.
            funcao: código da função orçamentária (ex: 10 para Saúde).

        Returns:
            Lista de dicts normalizados. Emendas com cod_ibge=None têm
            granularidade_perdida=True (requer resolução via TransfereGov/FNS).
        """
        params: dict = {
            "nomeAutor": nome_autor.upper().strip(),
            "ano": ano,
        }
        if funcao:
            params["codigoFuncao"] = funcao

        emendas: list[dict] = []
        async for page in self.client.get_paginated(
            "/emendas",
            params=params,
            page_param="pagina",
            items_key="",
            page_size=100,
        ):
            for raw in page:
                norm = self._normalizar_emenda(raw)
                # Aplica filtro de UF se solicitado (via prefixo do cod_ibge)
                if uf_filtro:
                    uf_emenda = self._derivar_uf(norm)
                    # Emendas sem cod_ibge (destino UF/Múltiplo) são incluídas
                    # mesmo com filtro_uf para posterior resolução
                    if uf_emenda and uf_emenda != uf_filtro.upper():
                        continue
                emendas.append(norm)

        perdidas = sum(1 for e in emendas if e["granularidade_perdida"])
        logger.info(
            f"Transparência: {len(emendas)} emendas para {nome_autor} ({ano}) — "
            f"{perdidas} com granularidade perdida (destino UF/Múltiplo)"
        )
        return emendas

    async def buscar_emenda_numero(
        self,
        numero_emenda: str,
    ) -> Optional[dict]:
        """
        Busca uma emenda específica pelo número.

        O número da emenda tem formato AAAANNNNNNNNN (13 dígitos):
          - AAAA = ano (ex: 2024)
          - NNN = código do órgão + sequencial

        Args:
            numero_emenda: número completo (ex: "202428550023").

        Returns:
            dict normalizado ou None se não encontrado.
        """
        try:
            data = await self.client.get_json(
                "/emendas",
                params={"numeroEmenda": numero_emenda},
            )
            # Resposta pode ser lista ou dict com envelope
            if isinstance(data, list) and data:
                return self._normalizar_emenda(data[0])
            elif isinstance(data, dict):
                items = data.get("dados") or data.get("data") or []
                if items:
                    return self._normalizar_emenda(items[0])
        except Exception as e:
            logger.warning(f"Transparência: erro ao buscar emenda {numero_emenda}: {e}")
        return None

    async def buscar_emendas_municipio(
        self,
        cod_ibge: int,
        ano: int,
    ) -> list[dict]:
        """
        Busca emendas recebidas por um município específico.

        LIMITAÇÃO IMPORTANTE:
          Apenas emendas com codigoMunicipioIBGE preenchido são retornadas.
          Emendas com destino 'UF' ou 'Múltiplo' NÃO aparecem nesta busca,
          mesmo que o município tenha recebido recursos via convênio/TE.

          Para descobrir TODAS as emendas de um município (incluindo as de
          destino 'Múltiplo'), é necessário complementar com TransfereGovCollector.

        Args:
            cod_ibge: código IBGE 7 dígitos do município (ex: 4205407).
            ano: ano de exercício.

        Returns:
            Lista de dicts normalizados. Todos terão granularidade_perdida=False.
        """
        params: dict = {
            "codigoMunicipioIBGE": str(cod_ibge),
            "ano": ano,
        }
        emendas: list[dict] = []
        async for page in self.client.get_paginated(
            "/emendas",
            params=params,
            page_param="pagina",
            items_key="",
            page_size=100,
        ):
            emendas.extend([self._normalizar_emenda(r) for r in page])

        logger.info(
            f"Transparência: {len(emendas)} emendas para município {cod_ibge} ({ano})"
        )
        return emendas

    async def buscar_emendas_uf(
        self,
        uf: str,
        ano: int,
        funcao: Optional[int] = None,
    ) -> list[dict]:
        """
        Busca emendas cujo codigoMunicipioIBGE começa com o prefixo da UF.

        Nota: NÃO usa o campo 'uf' da API (nome completo) — usa o prefixo
        do codigoMunicipioIBGE para derivar a UF de forma confiável.
        Retorna apenas emendas com cod_ibge preenchido (granularidade_perdida=False).

        Args:
            uf: sigla da UF (ex: "SC").
            ano: ano de exercício.
            funcao: código de função orçamentária (opcional).

        Returns:
            Lista de emendas com destino a municípios da UF.
        """
        uf = uf.upper()
        # Encontra prefixo IBGE da UF
        prefixo = next(
            (k for k, v in IBGE_UF_PREFIX.items() if v == uf), None
        )
        if not prefixo:
            logger.warning(f"Transparência: UF desconhecida '{uf}'")
            return []

        params: dict = {"ano": ano}
        if funcao:
            params["codigoFuncao"] = funcao

        emendas: list[dict] = []
        async for page in self.client.get_paginated(
            "/emendas",
            params=params,
            page_param="pagina",
            items_key="",
            page_size=100,
        ):
            for raw in page:
                ibge_raw = raw.get("codigoMunicipioIBGE")
                if ibge_raw and str(ibge_raw).startswith(prefixo):
                    emendas.append(self._normalizar_emenda(raw))

        logger.info(f"Transparência: {len(emendas)} emendas para municípios de {uf} ({ano})")
        return emendas

    # ------------------------------------------------------------------ #
    # Métodos de normalização                                             #
    # ------------------------------------------------------------------ #

    def _normalizar_emenda(self, raw: dict) -> dict:
        """
        Normaliza resposta do Portal da Transparência para schema canônico.

        CUIDADO CRÍTICO:
          - Campo 'uf' = NOME COMPLETO em maiúsculas ("SANTA CATARINA")
            → armazenado como 'uf_destino' no schema; NUNCA comparar com sigla.
          - Usar _derivar_uf() para obter sigla.
          - Quando codigoMunicipioIBGE é NULL → granularidade_perdida=True.

        Processamento de valores:
          Todos os valores monetários são convertidos de float para Decimal
          e armazenados como float no schema para compatibilidade com JSON.
          Precisão original é preservada (evita erros de arredondamento).
        """
        # Extração e validação do cod_ibge
        ibge_raw = raw.get("codigoMunicipioIBGE")
        cod_ibge: Optional[int] = None
        if ibge_raw:
            try:
                cod = int(str(ibge_raw).strip())
                # Código IBGE válido tem 7 dígitos (1000000 a 9999999)
                if 1_000_000 <= cod <= 9_999_999:
                    cod_ibge = cod
                else:
                    logger.debug(
                        f"Transparência: cod_ibge inválido '{ibge_raw}' — ignorado"
                    )
            except (ValueError, TypeError):
                pass

        # Conversão de valores monetários via Decimal para evitar erros float
        def _decimal(key: str) -> float:
            raw_val = raw.get(key)
            if raw_val is None:
                return 0.0
            try:
                return float(Decimal(str(raw_val)))
            except Exception:
                return 0.0

        # Classificação do tipo de RP
        tipo_rp_raw = str(raw.get("tipoResultadoPrimario") or "")
        tipo_rp = RP_MAP.get(tipo_rp_raw, "desconhecido")

        # RPE (Transferência Especial — EC 105/2019) sobrepõe o tipo RP
        if raw.get("transferenciaEspecial") is True:
            tipo_rp = "RPE_transferencia_especial"
        elif raw.get("tipoTransferencia") == "TE":
            tipo_rp = "RPE_transferencia_especial"

        # Extração do número da emenda com fallbacks entre nomes de campo
        numero = (
            raw.get("numeroEmenda")
            or raw.get("numero")
            or raw.get("nrEmenda")
            or ""
        )

        # Extração do ano com fallbacks
        ano_raw = raw.get("ano") or raw.get("anoOrçamento") or raw.get("anoOrcamento")
        try:
            ano = int(ano_raw) if ano_raw else 0
        except (ValueError, TypeError):
            ano = 0

        return {
            "numero_emenda": str(numero),
            "id_portal": raw.get("codigoEmenda") or raw.get("id"),
            "ano": ano,
            "nome_autor": raw.get("nomeAutor") or raw.get("autor", ""),
            "cod_autor_siop": raw.get("codigoAutor"),
            "cod_ibge_destino": cod_ibge,
            "uf_destino": raw.get("uf"),  # NOME COMPLETO do estado (não sigla!)
            "nome_municipio_destino": raw.get("nomeMunicipio") or raw.get("municipio"),
            "granularidade_perdida": cod_ibge is None,
            "funcao": raw.get("funcao") or raw.get("codigoFuncao"),
            "subfuncao": raw.get("subfuncao") or raw.get("codigoSubfuncao"),
            "objeto_resumido": (
                raw.get("objeto")
                or raw.get("descricaoObjeto")
                or raw.get("dscObjeto")
            ),
            "favorecido_nome": raw.get("nomeFavorecido"),
            "favorecido_cnpj": raw.get("cnpjFavorecido"),
            "valor_empenhado": _decimal("valorEmpenhado"),
            "valor_liquidado": _decimal("valorLiquidado"),
            "valor_pago": _decimal("valorPago"),
            "valor_rp_inscrito": _decimal("valorRpInscrito"),
            "tipo_rp": tipo_rp,
            "tipo_emenda": raw.get("tipoEmenda"),
            "impedimento_tecnico": bool(raw.get("impedimentoTecnico")),
            "transferencia_especial": bool(raw.get("transferenciaEspecial")),
            "fontes": ["portal_transparencia"],
        }

    def _derivar_uf(self, emenda: dict) -> Optional[str]:
        """
        Deriva a sigla da UF (ex: "SC") a partir do prefixo do cod_ibge.

        NÃO usa o campo 'uf_destino' (que contém nome completo como
        "SANTA CATARINA") — usa o prefixo de 2 dígitos do cod_ibge.

        Returns:
            Sigla da UF (ex: "SC") ou None se cod_ibge ausente.
        """
        cod = emenda.get("cod_ibge_destino")
        if cod:
            prefix = str(cod)[:2]
            return IBGE_UF_PREFIX.get(prefix)
        return None

    async def close(self):
        """Fecha o cliente HTTP."""
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
