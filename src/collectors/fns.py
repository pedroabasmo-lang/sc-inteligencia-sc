"""
Coletor FNS — Fundo Nacional de Saúde.

URL base: https://apifns.saude.gov.br/v1/gestor
Documentação: https://apifns.saude.gov.br/swagger-ui.html

Endpoints usados:

  GET /detalheamento/municipio/consulta
      Descrição: Repasses fundo-a-fundo por município e período.
      Params:
        codIBGE (str)          — código IBGE 6 dígitos (sem dígito verificador)
        mesAno (str)           — período no formato "MM/YYYY" (ex: "01/2024")
        anoCompetencia (int)   — ano de competência (retorna todos os meses do ano)
      Resposta: lista de objetos de repasse com:
        descricaoPrograma (str) — nome do programa de saúde
        competencia (str)       — "MM/YYYY"
        valor (float)           — valor repassado
        portaria (str)          — portaria de liberação
        descricaoBloco (str)    — bloco de financiamento (ex: "ATENÇÃO BÁSICA")

  GET /detalheamento/programa/consulta
      Descrição: Repasses por programa/portaria específica.
      Params:
        numeroPortaria (str)   — número da portaria ministerial
        uf (str)               — sigla da UF (opcional)
        codIBGE (str)          — código IBGE 6 dígitos (opcional)
      Resposta: similar ao endpoint de município

  GET /detalheamento/bloco/consulta
      Descrição: Repasses por bloco de financiamento do SUS.
      Params:
        codBloco (int)         — código do bloco
        anoCompetencia (int)   — ano
        uf (str)               — UF (opcional)
      Blocos principais:
        1 = Atenção Básica (PAB/BAFAB)
        2 = Atenção de Média e Alta Complexidade
        3 = Vigilância em Saúde
        4 = Assistência Farmacêutica
        5 = Gestão do SUS
        6 = Investimentos na Rede de Serviços

Rate limit: ~3 req/s (conservador — sem documentação oficial de limite).
Autenticação: não requer (dados públicos).

INTEGRAÇÃO COM EMENDAS DE SAÚDE:
  Emendas parlamentares da função orçamentária 10 (Saúde) são frequentemente
  distribuídas via blocos de financiamento do SUS (especialmente Bloco 1 -
  Atenção Básica). A relação entre emenda e portaria de liberação permite
  rastrear quais municípios receberam recursos de uma emenda de saúde.

  Fluxo típico:
    1. Emenda RP6/RPE de saúde → portaria ministerial de liberação
    2. Portaria → repasse fundo-a-fundo via FNS para municípios
    3. FNS API permite consultar por portaria → municípios beneficiados

  Para emendas com destino 'Múltiplo' de saúde, complementar a busca
  TransfereGov com consulta ao FNS por portaria vinculada à emenda.

Exemplo de resposta de /detalheamento/municipio/consulta:
[
  {
    "codigoMunicipio": "420540",
    "nomeMunicipio": "Florianópolis",
    "descricaoPrograma": "INCENTIVO - IMPLANTAÇÃO E IMPLEMENTAÇÃO DAS REDES TEMÁTICAS",
    "descricaoBloco": "ATENÇÃO DE MÉDIA E ALTA COMPLEXIDADE",
    "competencia": "01/2024",
    "valor": 125000.00,
    "portaria": "3.994/2023",
    "dataRepasse": "2024-01-15"
  },
  ...
]
"""
import logging
from decimal import Decimal
from typing import Optional

from src.utils.http import APIClient
from src.config import settings

logger = logging.getLogger("sc_inteligencia.collectors.fns")

# Blocos de financiamento do SUS (Lei 8080/90, Portaria GM/MS 3.992/2017)
BLOCOS_SUS: dict[int, str] = {
    1: "Atenção Básica",
    2: "Atenção de Média e Alta Complexidade",
    3: "Vigilância em Saúde",
    4: "Assistência Farmacêutica",
    5: "Gestão do SUS",
    6: "Investimentos na Rede de Serviços",
}

# Palavras-chave para identificar repasses de atenção básica
_KEYWORDS_ATENCAO_BASICA = frozenset([
    "ATENÇÃO BÁSICA", "ATENCAO BASICA",
    "PAB", "BAFAB", "ACS", "AGENTE COMUNITÁRIO",
    "SAÚDE DA FAMÍLIA", "SAUDE DA FAMILIA",
    "ESF", "UBS",
])


class FNSCollector:
    """
    Coleta repasses do Fundo Nacional de Saúde (FNS) por município.

    O FNS é o mecanismo federal de transferência de recursos financeiros
    ao SUS (Sistema Único de Saúde). Os repasses são fundo-a-fundo:
    diretamente do Fundo Nacional de Saúde para os Fundos Municipais
    de Saúde (FMS), sem necessidade de convênio.

    Papel no sc-inteligencia:
      Resolver emendas de saúde (função 10) com destino 'Múltiplo'.
      Emendas de saúde frequentemente são executadas via portarias
      ministeriais que distribuem recursos para todos os municípios
      de uma UF ou do Brasil — identificáveis via número de portaria.

    Uso básico:
        async with FNSCollector() as collector:
            repasses = await collector.buscar_repasses_municipio(4205407, 2024)
            por_bloco = await collector.buscar_repasses_bloco(1, 2024, uf="SC")
    """

    def __init__(self):
        self.client = APIClient(
            base_url=settings.FNS_API,
            rate_limit=3,
        )

    async def buscar_repasses_municipio(
        self,
        cod_ibge: int,
        ano: int,
        mes: Optional[int] = None,
    ) -> list[dict]:
        """
        Busca repasses FNS recebidos por um município em um período.

        Args:
            cod_ibge: código IBGE 7 dígitos (converte internamente para 6 dígitos
                      removendo o dígito verificador).
            ano: ano de competência.
            mes: mês específico (1-12). Se None, busca o ano todo via anoCompetencia.

        Returns:
            Lista de dicts normalizados com: cod_ibge, programa, bloco, competencia,
            valor, portaria, data_repasse.
        """
        # FNS usa código de 6 dígitos (sem dígito verificador)
        cod_6 = str(cod_ibge)[:6]

        if mes:
            params: dict = {"codIBGE": cod_6, "mesAno": f"{mes:02d}/{ano}"}
        else:
            params = {"codIBGE": cod_6, "anoCompetencia": ano}

        try:
            data = await self.client.get_json(
                "/detalheamento/municipio/consulta",
                params=params,
            )
            # A API pode retornar lista direta ou objeto com "data"/"dados"
            if isinstance(data, list):
                repasses = data
            elif isinstance(data, dict):
                repasses = (
                    data.get("data")
                    or data.get("dados")
                    or data.get("content")
                    or []
                )
            else:
                repasses = []

            result = [self._normalizar(r, cod_ibge) for r in repasses]
            logger.debug(
                f"FNS: {len(result)} repasses para município {cod_ibge} ({ano}/{mes or 'all'})"
            )
            return result
        except Exception as e:
            logger.warning(
                f"FNS: erro ao buscar repasses do município {cod_ibge} ({ano}/{mes}): {e}"
            )
            return []

    async def buscar_por_portaria(
        self,
        numero_portaria: str,
        uf: Optional[str] = None,
        cod_ibge: Optional[int] = None,
    ) -> list[dict]:
        """
        Busca repasses vinculados a uma portaria ministerial específica.

        As portarias de liberação de emendas de saúde são publicadas no
        Diário Oficial da União (DOU) e identificam quais municípios ou
        estados recebem recursos vinculados a uma emenda parlamentar de saúde.

        Args:
            numero_portaria: número da portaria (ex: "3994", "3.994/2023").
            uf: sigla da UF para filtrar (opcional).
            cod_ibge: código IBGE para filtrar município específico (opcional).

        Returns:
            Lista de dicts normalizados. Retorna [] em caso de erro ou
            endpoint indisponível (endpoint experimental).

        Nota:
            Endpoint experimental — disponibilidade na API real não garantida.
            Verificar swagger para confirmar.
        """
        # Normaliza número de portaria removendo pontuação
        portaria_norm = numero_portaria.replace(".", "").replace("/", "").strip()

        params: dict = {"numeroPortaria": portaria_norm}
        if uf:
            params["uf"] = uf.upper()
        if cod_ibge:
            params["codIBGE"] = str(cod_ibge)[:6]

        try:
            data = await self.client.get_json(
                "/detalheamento/programa/consulta",
                params=params,
            )
            if isinstance(data, list):
                repasses = data
            elif isinstance(data, dict):
                repasses = data.get("data") or data.get("dados") or []
            else:
                repasses = []

            # Para repasses sem cod_ibge explícito, tentar extrair do contexto
            result = []
            for r in repasses:
                cod = self._extrair_cod_ibge(r)
                if cod:
                    result.append(self._normalizar(r, cod))
            return result
        except Exception as e:
            logger.warning(f"FNS portaria {numero_portaria}: {e}")
            return []

    async def buscar_repasses_bloco(
        self,
        cod_bloco: int,
        ano: int,
        uf: Optional[str] = None,
    ) -> list[dict]:
        """
        Busca repasses por bloco de financiamento do SUS para um ano.

        Útil para análises agregadas: quanto foi repassado para Atenção Básica
        em SC em 2024, por exemplo.

        Args:
            cod_bloco: código do bloco (ver BLOCOS_SUS: 1=Atenção Básica, etc.).
            ano: ano de competência.
            uf: sigla da UF para filtrar (opcional).

        Returns:
            Lista de dicts com repasses de todos os municípios no bloco/ano/uf.
        """
        params: dict = {"codBloco": cod_bloco, "anoCompetencia": ano}
        if uf:
            params["uf"] = uf.upper()

        try:
            data = await self.client.get_json(
                "/detalheamento/bloco/consulta",
                params=params,
            )
            if isinstance(data, list):
                repasses = data
            elif isinstance(data, dict):
                repasses = data.get("data") or data.get("dados") or []
            else:
                repasses = []

            result = []
            for r in repasses:
                cod = self._extrair_cod_ibge(r)
                if cod:
                    result.append(self._normalizar(r, cod))
            logger.info(
                f"FNS bloco {cod_bloco} ({BLOCOS_SUS.get(cod_bloco, '?')}): "
                f"{len(result)} repasses para {uf or 'BR'} em {ano}"
            )
            return result
        except Exception as e:
            logger.warning(f"FNS bloco {cod_bloco}/{ano}: {e}")
            return []

    async def buscar_sus_piso_municipio(
        self,
        cod_ibge: int,
        competencia: str,
    ) -> Optional[Decimal]:
        """
        Retorna valor total do Piso de Atenção Básica (PAB/BAFAB) recebido
        pelo município em uma competência específica.

        O PAB é o principal mecanismo de financiamento da Atenção Básica
        (UBS, ESF, Agentes Comunitários de Saúde, etc.).

        Args:
            cod_ibge: código IBGE 7 dígitos do município.
            competencia: período no formato "YYYY-MM" (ex: "2024-01").

        Returns:
            Valor total em Decimal, ou None se sem dados de atenção básica.
        """
        try:
            ano_str, mes_str = competencia.split("-")
            ano, mes = int(ano_str), int(mes_str)
        except ValueError as e:
            logger.warning(f"FNS: formato de competência inválido '{competencia}': {e}")
            return None

        repasses = await self.buscar_repasses_municipio(cod_ibge, ano, mes)

        total_basica = Decimal("0")
        for r in repasses:
            programa_upper = (r.get("programa") or r.get("bloco") or "").upper()
            if any(kw in programa_upper for kw in _KEYWORDS_ATENCAO_BASICA):
                total_basica += Decimal(str(r.get("valor", 0)))

        return total_basica if total_basica > 0 else None

    async def consolidar_municipios_uf(
        self,
        uf: str,
        ano: int,
    ) -> dict[int, float]:
        """
        Consolida total de repasses FNS por município de uma UF em um ano.

        Retorna mapeamento cod_ibge → valor_total_anual para todos os
        municípios da UF que receberam repasses no período.

        Args:
            uf: sigla da UF (ex: "SC").
            ano: ano de competência.

        Returns:
            dict mapeando cod_ibge (int) → valor total em float.
        """
        # Busca por bloco para todos os municípios da UF (mais eficiente)
        totais: dict[int, float] = {}

        for cod_bloco in BLOCOS_SUS:
            repasses = await self.buscar_repasses_bloco(cod_bloco, ano, uf=uf)
            for r in repasses:
                cod = r.get("cod_ibge")
                if cod:
                    totais[cod] = totais.get(cod, 0.0) + r.get("valor", 0.0)

        logger.info(
            f"FNS consolidado: {len(totais)} municípios da {uf} com repasses em {ano}"
        )
        return totais

    # ------------------------------------------------------------------ #
    # Métodos de normalização                                             #
    # ------------------------------------------------------------------ #

    def _normalizar(self, raw: dict, cod_ibge: int) -> dict:
        """
        Normaliza repasse FNS para formato canônico.

        A API FNS usa diferentes nomes de campos em diferentes endpoints.
        Este método unifica os campos mais comuns.
        """
        return {
            "cod_ibge": cod_ibge,
            "programa": (
                raw.get("descricaoPrograma")
                or raw.get("programa")
                or raw.get("nmPrograma")
                or ""
            ),
            "bloco": (
                raw.get("descricaoBloco")
                or raw.get("bloco")
                or raw.get("nmBloco")
                or ""
            ),
            "competencia": (
                raw.get("competencia")
                or raw.get("mesAno")
                or raw.get("dtCompetencia")
                or ""
            ),
            "valor": float(
                Decimal(
                    str(
                        raw.get("valor")
                        or raw.get("valorRepasse")
                        or raw.get("vlRepasse")
                        or 0
                    )
                )
            ),
            "portaria": (
                raw.get("portaria")
                or raw.get("numeroPortaria")
                or raw.get("nrPortaria")
            ),
            "data_repasse": raw.get("dataRepasse") or raw.get("dtRepasse"),
            "fonte": "fns",
        }

    def _extrair_cod_ibge(self, raw: dict) -> Optional[int]:
        """
        Tenta extrair cod_ibge de uma resposta FNS com múltiplos campos candidatos.

        A API FNS usa variações de nomes de campo entre endpoints.
        """
        candidatos = [
            raw.get("codigoMunicipio"),
            raw.get("codIBGE"),
            raw.get("cdIbge"),
            raw.get("cdMunicipio"),
            raw.get("codigoIBGE"),
        ]
        for candidato in candidatos:
            if candidato:
                try:
                    return int(str(candidato).strip())
                except (ValueError, TypeError):
                    continue
        return None

    async def close(self):
        """Fecha o cliente HTTP."""
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
