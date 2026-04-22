"""
Coletor TransfereGov — Resolve emendas com destino 'Múltiplo' ou 'UF'.

EXISTEM DUAS APIS COMPLEMENTARES:

1. API PostgREST (ENDPOINT CONFIRMADO VIA CURL — PRIORIDADE MÁXIMA)
   URL base : https://api.transferegov.gestao.gov.br/transferenciasespeciais
   Tecnologia: PostgREST (filtros via operadores no querystring)
   Documentação: https://docs.api.transferegov.gestao.gov.br/transferencias-especiais/

   Endpoint principal:
     GET /plano_acao_especial
       Filtros PostgREST (operadores: eq., ilike., gte., lte.):
         numero_emenda_parlamentar_plano_acao=eq.202428550023
         nome_parlamentar_emenda_plano_acao=ilike.*UCZAI*
         ano_plano_acao=eq.2024
         uf_beneficiario_plano_acao=eq.SC

       Campos retornados:
         id_plano_acao, codigo_plano_acao, ano_plano_acao,
         modalidade_plano_acao, situacao_plano_acao,
         cnpj_beneficiario_plano_acao, nome_beneficiario_plano_acao,
         uf_beneficiario_plano_acao,
         nome_parlamentar_emenda_plano_acao,
         ano_emenda_parlamentar_plano_acao,
         codigo_parlamentar_emenda_plano_acao,     # ex: "2855" para Uczai
         sequencial_emenda_parlamentar_plano_acao,
         numero_emenda_parlamentar_plano_acao,     # ex: "202428550022"
         codigo_emenda_parlamentar_formatado_plano_acao,
         valor_custeio_plano_acao,
         valor_investimento_plano_acao,
         id_programa

       IMPORTANTE: Não há cod_ibge diretamente. O cod_ibge deve ser obtido
       cruzando cnpj_beneficiario_plano_acao com BrasilAPI /cnpj/{cnpj}
       (campo municipio + uf) ou com lookup de CNPJ municipal da Receita.

   Exemplo testado (Pedro Uczai 2024, emenda 202428550022):
     Resultado: 5 municípios encontrados:
       Nova Itaberaba     R$  400.000
       Balneário Camboriú R$ 100.000
       Santa Terezinha    R$  100.000
       Saltinho            R$  300.000
       São Miguel d'Oeste R$  500.000

2. API REST convencional (fallback se PostgREST não retornar resultados)
   URL base: https://api.transferegov.gestao.gov.br
   Documentação: https://api.transferegov.gestao.gov.br/swagger-ui.html

   GET /transferencias/transferencias-especiais
       Params: nrEmenda, anoEmenda, cdMunicipioIbge, page (base 0), size
       Resposta: paginação Spring {content, totalElements, totalPages}

   GET /convenios/convenios
       Params: nrEmenda, anoEmenda, cdMunicipioIbge, page, size
       Resposta: paginação Spring

Autenticação:
  Sem token: dados básicos públicos.
  Com TRANSFEREGOV_TOKEN: campos adicionais desbloqueados.

Rate limit: ~10 req/s (empírico). Semáforo configurado em 5 req/s.

PROBLEMA QUE ESTE COLETOR RESOLVE:
  O Portal da Transparência exporta emendas com codigoMunicipioIBGE=NULL
  quando destino é 'UF' ou 'Múltiplo'. Este coletor usa TransfereGov como
  segunda fonte para discriminar os municípios beneficiários reais.

Estrategia em cascata buscar_por_numero_emenda():
  Camada 0: API PostgREST /plano_acao_especial (endpoint confirmado)
  Camada 1: API REST /transferencias/transferencias-especiais (RPE)
  Camada 2: API REST /convenios/convenios (RP6/7/8)
  Resultado: lista de municípios com valor e confiança 1.0 quando cod_ibge direto,
             ou 0.8 quando cod_ibge derivado via CNPJ lookup.
"""
import logging
from decimal import Decimal
from typing import Optional
import httpx

from src.utils.http import APIClient
from src.config import settings

logger = logging.getLogger("sc_inteligencia.collectors.transferegov")


class TransfereGovCollector:
    """
    Resolve o problema central do projeto: emendas com destino 'UF' ou 'Múltiplo'
    no Portal da Transparência não têm município discriminado no campo
    codigoMunicipioIBGE.

    Esta classe usa a API TransfereGov como segunda fonte, que retorna os instrumentos
    de repasse (convênios, Transferências Especiais, TEDs) com cod_ibge do município
    beneficiário de cada instrumento individual.

    Fluxo de resolução:
      1. Portal da Transparência retorna emenda com cod_ibge=NULL, destino='Múltiplo'
      2. TransfereGovCollector.buscar_por_numero_emenda(numero_emenda) →
         retorna lista de municípios com valores individuais
      3. Pipeline consolida os valores por município (cod_ibge canônico)

    Uso básico:
        async with TransfereGovCollector() as collector:
            resultado = await collector.buscar_por_numero_emenda("202428550023")
            # resultado: [{"cod_ibge": 4217204, "nome_municipio": "São Miguel do Oeste",
            #              "valor_pago": 1500000.0, "tipo_instrumento": "RP6_individual", ...}]
    """

    def __init__(self):
        headers: dict = {}
        if settings.TRANSFEREGOV_TOKEN:
            headers["Authorization"] = f"Bearer {settings.TRANSFEREGOV_TOKEN}"

        self.client = APIClient(
            base_url=settings.TRANSFEREGOV_API,
            headers=headers,
            rate_limit=5,
        )
        # Cliente dedicado para a API PostgREST (endpoint confirmado via curl)
        self._postgrest_base = settings.TRANSFEREGOV_POSTGREST_API
        self._postgrest_headers = {
            **headers,
            "Accept": "application/json",
            "Accept-Profile": "public",
        }

    async def buscar_plano_acao_postgrest(
        self,
        numero_emenda: Optional[str] = None,
        nome_parlamentar: Optional[str] = None,
        codigo_parlamentar: Optional[str] = None,
        ano: Optional[int] = None,
        uf: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict]:
        """
        Consulta o endpoint PostgREST /plano_acao_especial (endpoint confirmado via curl).

        Esta é a CAMADA 0 da cascata — mais confiável e com dados estruturados.

        Sintaxe de filtro PostgREST:
          campo=eq.VALOR      (igual)
          campo=ilike.*TEXTO* (busca case-insensitive com wildcard)
          campo=gte.VALOR     (maior ou igual)
          campo=lte.VALOR     (menor ou igual)

        Campos retornados (não há cod_ibge diretamente):
          cnpj_beneficiario_plano_acao  — CNPJ do beneficiário
          nome_beneficiario_plano_acao  — nome do beneficiário (município ou entidade)
          uf_beneficiario_plano_acao    — sigla da UF (ex: "SC")
          valor_custeio_plano_acao      — valor de custeio
          valor_investimento_plano_acao — valor de investimento
          situacao_plano_acao           — situação do plano de ação

        O cod_ibge deve ser obtido via BrasilAPI:
          GET https://brasilapi.com.br/api/cnpj/v1/{cnpj}
          Campo: municipio + uf (buscar código IBGE no lookup)

        Args:
            numero_emenda:     número exato da emenda (ex: "202428550023")
            nome_parlamentar:  parte do nome do parlamentar (wildcard automático)
            codigo_parlamentar: código TSE do parlamentar (ex: "2855" para Uczai)
            ano:               ano da emenda (ex: 2024)
            uf:                sigla da UF beneficiária (ex: "SC")
            limit:             máx. de registros por requisição (PostgREST usa Range)
            offset:            offset para paginação manual

        Returns:
            Lista de dicts com todos os campos da tabela plano_acao_especial.
        """
        params: dict = {"limit": limit, "offset": offset}

        if numero_emenda:
            params["numero_emenda_parlamentar_plano_acao"] = f"eq.{numero_emenda}"
        if nome_parlamentar:
            params["nome_parlamentar_emenda_plano_acao"] = f"ilike.*{nome_parlamentar.upper()}*"
        if codigo_parlamentar:
            params["codigo_parlamentar_emenda_plano_acao"] = f"eq.{codigo_parlamentar}"
        if ano:
            params["ano_plano_acao"] = f"eq.{ano}"
        if uf:
            params["uf_beneficiario_plano_acao"] = f"eq.{uf.upper()}"

        url = f"{self._postgrest_base}/plano_acao_especial"
        logger.info(
            f"TransfereGov PostgREST: GET {url} params={params}"
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, params=params, headers=self._postgrest_headers)
                resp.raise_for_status()
                data = resp.json()
                logger.info(f"TransfereGov PostgREST: {len(data)} registros retornados")
                return data if isinstance(data, list) else []
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"TransfereGov PostgREST HTTP {e.response.status_code}: {e}"
            )
            return []
        except Exception as e:
            logger.warning(f"TransfereGov PostgREST falhou: {e}")
            return []

    async def buscar_por_numero_emenda(self, numero_emenda: str) -> list[dict]:
        """
        Chave principal para resolução do problema 'Múltiplo'/'UF'.

        Dado um número de emenda (ex: "202428550023"), busca todos os instrumentos
        de repasse associados, retornando municípios identificados com cod_ibge.

        Estratégia de resolução em cascata (3 camadas):
          Camada 0: PostgREST /plano_acao_especial (endpoint confirmado via curl)
                    Retorna CNPJ + nome + UF + valores. cod_ibge derivado via lookup.
          Camada 1: API REST /transferencias/transferencias-especiais (RPE Emenda Pix)
          Camada 2: API REST /convenios/convenios (RP6 individual, RP7 bancada)

        A cascata para na primeira camada que retorna resultados.

        Args:
            numero_emenda: número da emenda no formato AAAA+sequencial
                           (ex: "202428550023"). Aceita formatos com hífens/pontos.

        Returns:
            Lista de dicts com:
              cod_ibge (int)          — código IBGE 7 dígitos (0 se não resolvido)
              nome_municipio (str)    — nome do município ou beneficiário
              uf (str)                — sigla da UF
              valor_pago (float)      — valor efetivamente pago/transferido
              valor_empenhado (float) — valor empenhado/contratado
              nr_instrumento (str)    — código do plano/convênio/TE
              tipo_instrumento (str)  — "RPE_plano_acao" | "RPE_transferencia_especial" | "RP6_individual"
              numero_emenda (str)     — número da emenda de origem
              situacao (str)          — situação do instrumento
              confianca (float)       — 1.0 direto da API; 0.8 via CNPJ lookup
              fonte (str)             — "transferegov_postgrest" | "transferegov_te" | "transferegov_convenio"
        """
        resultados: list[dict] = []

        # Camada 0: PostgREST (endpoint confirmado via curl — prioridade máxima)
        try:
            pg_raw = await self.buscar_plano_acao_postgrest(numero_emenda=numero_emenda)
            if pg_raw:
                for item in pg_raw:
                    norm = self._normalizar_plano_acao(item, numero_emenda)
                    if norm:
                        resultados.append(norm)
                logger.info(
                    f"TransfereGov PostgREST: {len(resultados)} registros para emenda {numero_emenda}"
                )
                # Se PostgREST retornou dados, retorna direto sem acionar fallback
                return self._dedup(resultados)
        except Exception as e:
            logger.warning(f"TransfereGov PostgREST (camada 0) falhou para {numero_emenda}: {e}")

        # Camada 1: API REST — Transferências Especiais (RPE EC 105/2019)
        try:
            te = await self._buscar_transferencias_especiais(numero_emenda)
            resultados.extend(te)
            logger.info(
                f"TransfereGov TE: {len(te)} registros para emenda {numero_emenda}"
            )
        except Exception as e:
            logger.warning(f"TransfereGov TE (camada 1) falhou para {numero_emenda}: {e}")

        # Camada 2: API REST — Convênios clássicos (RP6/7/8)
        try:
            conv = await self._buscar_convenios(numero_emenda)
            resultados.extend(conv)
            logger.info(
                f"TransfereGov Conv: {len(conv)} registros para emenda {numero_emenda}"
            )
        except Exception as e:
            logger.warning(f"TransfereGov Conv (camada 2) falhou para {numero_emenda}: {e}")

        unicos = self._dedup(resultados)
        logger.info(
            f"TransfereGov: {len(unicos)} municípios únicos para emenda {numero_emenda}"
        )
        return unicos

    def _dedup(self, resultados: list[dict]) -> list[dict]:
        """Remove duplicatas por (cod_ibge, nr_instrumento)."""
        vistos: set[tuple] = set()
        unicos: list[dict] = []
        for r in resultados:
            chave = (r.get("cod_ibge"), r.get("nr_instrumento"))
            if chave not in vistos:
                vistos.add(chave)
                unicos.append(r)
        return unicos

    def _normalizar_plano_acao(
        self,
        raw: dict,
        numero_emenda: str,
    ) -> Optional[dict]:
        """
        Normaliza resposta do endpoint PostgREST /plano_acao_especial.

        NOTA: Não há cod_ibge diretamente. O campo cnpj_beneficiario_plano_acao
        pode ser cruzado com BrasilAPI /cnpj/v1/{cnpj} para obter o município.
        Por ora, cod_ibge=0 e confianca=0.8 — o matcher pode resolver depois.

        Campos do raw (PostgREST /plano_acao_especial):
          cnpj_beneficiario_plano_acao, nome_beneficiario_plano_acao,
          uf_beneficiario_plano_acao, valor_custeio_plano_acao,
          valor_investimento_plano_acao, situacao_plano_acao,
          codigo_plano_acao, id_plano_acao
        """
        cnpj = raw.get("cnpj_beneficiario_plano_acao", "")
        nome = raw.get("nome_beneficiario_plano_acao", "")
        uf = raw.get("uf_beneficiario_plano_acao", "")

        # Soma custeio + investimento como valor total
        custeio = Decimal(str(raw.get("valor_custeio_plano_acao") or 0))
        investimento = Decimal(str(raw.get("valor_investimento_plano_acao") or 0))
        valor_total = custeio + investimento

        codigo_plano = raw.get("codigo_plano_acao") or raw.get("id_plano_acao", "")

        return {
            "cod_ibge": 0,              # será resolvido via CNPJ lookup pelo matcher
            "nome_municipio": nome,
            "uf": uf,
            "cnpj_beneficiario": cnpj,  # campo extra para resolver cod_ibge
            "valor_pago": float(valor_total),
            "valor_empenhado": float(valor_total),
            "nr_instrumento": str(codigo_plano),
            "tipo_instrumento": "RPE_plano_acao",
            "numero_emenda": numero_emenda,
            "situacao": raw.get("situacao_plano_acao"),
            "codigo_parlamentar": raw.get("codigo_parlamentar_emenda_plano_acao"),
            "nome_parlamentar": raw.get("nome_parlamentar_emenda_plano_acao"),
            "ano_emenda": raw.get("ano_emenda_parlamentar_plano_acao"),
            "confianca": 0.8,           # sem cod_ibge direto; matcher resolve para 1.0
            "fonte": "transferegov_postgrest",
        }

    async def _buscar_transferencias_especiais(
        self,
        numero_emenda: str,
    ) -> list[dict]:
        """
        Busca na API de Transferências Especiais (Emenda Pix EC 105/2019).

        Endpoint: GET /transferencias/transferencias-especiais
        Params: nrEmenda={numero_emenda}, page=N, size=50

        Resposta esperada (Spring pagination):
        {
          "content": [{
            "idTransferenciaEspecial": 12345,
            "nrEmenda": "202428550023",
            "vlTransferenciaEspecial": 1000000.00,
            "municipio": {
              "cdIbge": "4217204",
              "nmMunicipio": "São Miguel do Oeste",
              "sgUf": "SC"
            },
            "stTransferencia": "PAGO",
            "dtPagamento": "2024-06-15"
          }],
          "totalElements": 3,
          "totalPages": 1,
          "number": 0
        }
        """
        items: list[dict] = []
        async for page in self.client.get_paginated(
            "/transferencias/transferencias-especiais",
            params={"nrEmenda": numero_emenda},
            items_key="content",
            page_param="page",
            page_size_param="size",
            page_size=50,
        ):
            for item in page:
                normalizado = self._normalizar_te(item, numero_emenda)
                if normalizado:
                    items.append(normalizado)
        return items

    async def _buscar_convenios(self, numero_emenda: str) -> list[dict]:
        """
        Busca convênios vinculados ao número de emenda.

        Endpoint: GET /convenios/convenios
        Params: nrEmenda={numero_emenda}, page=N, size=50

        Resposta esperada (Spring pagination):
        {
          "content": [{
            "nrConvenio": "987654",
            "nrEmenda": "202428550023",
            "vlConvenio": 800000.00,
            "vlDesembolsado": 750000.00,
            "municipio": {
              "cdIbge": "4205407",
              "nmMunicipio": "Florianópolis",
              "sgUf": "SC"
            },
            "situacao": "ADIMPLENTE",
            "objeto": "Aquisição de equipamentos hospitalares para UPA"
          }]
        }
        """
        items: list[dict] = []
        async for page in self.client.get_paginated(
            "/convenios/convenios",
            params={"nrEmenda": numero_emenda},
            items_key="content",
            page_param="page",
            page_size_param="size",
            page_size=50,
        ):
            for item in page:
                normalizado = self._normalizar_convenio(item, numero_emenda)
                if normalizado:
                    items.append(normalizado)
        return items

    async def buscar_transferencias_municipio(
        self,
        cod_ibge: int,
        ano: Optional[int] = None,
    ) -> list[dict]:
        """
        Busca todas as Transferências Especiais recebidas por um município.

        Útil para verificação cruzada: dado o município, quais emendas recebeu?
        Permite construir a visão inversa (município → emendas recebidas).

        Args:
            cod_ibge: código IBGE 7 dígitos do município.
            ano: filtra por anoEmenda (opcional).

        Returns:
            Lista de dicts normalizados de Transferências Especiais.
        """
        params: dict = {"cdMunicipioIbge": str(cod_ibge)}
        if ano:
            params["anoEmenda"] = ano

        items: list[dict] = []
        async for page in self.client.get_paginated(
            "/transferencias/transferencias-especiais",
            params=params,
            items_key="content",
            page_param="page",
            page_size_param="size",
            page_size=50,
        ):
            for item in page:
                norm = self._normalizar_te(item, item.get("nrEmenda", ""))
                if norm:
                    items.append(norm)
        return items

    async def buscar_convenios_municipio(
        self,
        cod_ibge: int,
        ano: Optional[int] = None,
    ) -> list[dict]:
        """
        Busca todos os convênios recebidos por um município.

        Args:
            cod_ibge: código IBGE 7 dígitos do município.
            ano: filtra por anoEmenda (opcional).

        Returns:
            Lista de dicts normalizados de convênios.
        """
        params: dict = {"cdMunicipioIbge": str(cod_ibge)}
        if ano:
            params["anoEmenda"] = ano

        items: list[dict] = []
        async for page in self.client.get_paginated(
            "/convenios/convenios",
            params=params,
            items_key="content",
            page_param="page",
            page_size_param="size",
            page_size=50,
        ):
            for item in page:
                norm = self._normalizar_convenio(item, item.get("nrEmenda", ""))
                if norm:
                    items.append(norm)
        return items

    async def detalhe_transferencia(self, id_te: int) -> Optional[dict]:
        """
        Busca detalhe completo de uma Transferência Especial pelo ID.

        Retorna campos adicionais não disponíveis na listagem.

        Args:
            id_te: ID da Transferência Especial.

        Returns:
            dict normalizado ou None em caso de erro.
        """
        try:
            raw = await self.client.get_json(
                f"/transferencias/transferencias-especiais/{id_te}"
            )
            return self._normalizar_te(raw, raw.get("nrEmenda", ""))
        except Exception as e:
            logger.warning(f"TransfereGov: erro ao buscar TE {id_te}: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Métodos de normalização                                             #
    # ------------------------------------------------------------------ #

    def _normalizar_te(
        self,
        raw: dict,
        numero_emenda: str,
    ) -> Optional[dict]:
        """
        Normaliza resposta de Transferência Especial para schema canônico.

        Tenta múltiplos campos candidatos para cod_ibge pois a API pode
        variar entre versões da documentação:
          - municipio.cdIbge       (campo principal documentado)
          - municipio.codigoIBGE   (alias observado em algumas respostas)
          - cdMunicipio            (campo legado)
          - codigoMunicipioIBGE    (campo legado alternativo)

        Returns:
            dict normalizado ou None se cod_ibge não puder ser extraído.
        """
        mun = raw.get("municipio") or raw.get("entidade") or {}
        cod_ibge_str = (
            mun.get("cdIbge")
            or mun.get("codigoIBGE")
            or raw.get("cdMunicipio")
            or raw.get("codigoMunicipioIBGE")
        )
        if not cod_ibge_str:
            logger.debug(f"TransfereGov TE: cod_ibge ausente em item {raw.get('idTransferenciaEspecial')}")
            return None

        try:
            cod_ibge = int(str(cod_ibge_str).strip())
        except (ValueError, TypeError):
            return None

        valor = Decimal(
            str(
                raw.get("vlTransferenciaEspecial")
                or raw.get("valor")
                or raw.get("vlRepasse")
                or 0
            )
        )

        return {
            "cod_ibge": cod_ibge,
            "nome_municipio": mun.get("nmMunicipio") or mun.get("nome", ""),
            "uf": mun.get("sgUf") or mun.get("uf", ""),
            "valor_pago": float(valor),
            "valor_empenhado": float(valor),  # TE: empenhado == pago
            "nr_instrumento": str(
                raw.get("idTransferenciaEspecial") or raw.get("id", "")
            ),
            "tipo_instrumento": "RPE_transferencia_especial",
            "numero_emenda": numero_emenda,
            "situacao": raw.get("stTransferencia") or raw.get("situacao"),
            "data_pagamento": raw.get("dtPagamento"),
            "confianca": 1.0,
            "fonte": "transferegov_te",
        }

    def _normalizar_convenio(
        self,
        raw: dict,
        numero_emenda: str,
    ) -> Optional[dict]:
        """
        Normaliza resposta de Convênio para schema canônico.

        Para convênios, o proponente pode ser município, estado ou entidade privada.
        Apenas convênios com cod_ibge de município são retornados (entidades
        sem cod_ibge são ignoradas pois não podem ser georreferenciadas).

        Returns:
            dict normalizado ou None se cod_ibge ausente ou inválido.
        """
        mun = raw.get("municipio") or raw.get("proponente") or {}
        cod_ibge_str = (
            mun.get("cdIbge")
            or mun.get("codigoIBGE")
            or raw.get("cdMunicipio")
            or mun.get("codigo")
        )
        if not cod_ibge_str:
            logger.debug(
                f"TransfereGov Conv: cod_ibge ausente em convênio {raw.get('nrConvenio')}"
            )
            return None

        try:
            cod_ibge = int(str(cod_ibge_str).strip())
        except (ValueError, TypeError):
            return None

        # Para convênios, valor_empenhado = valor total contratado
        valor_total = Decimal(
            str(raw.get("vlConvenio") or raw.get("valor") or raw.get("vlGlobal") or 0)
        )
        # valor_pago = desembolsado efetivamente
        valor_pago = Decimal(
            str(
                raw.get("vlDesembolsado")
                or raw.get("valorPago")
                or raw.get("vlRepassado")
                or valor_total
            )
        )

        return {
            "cod_ibge": cod_ibge,
            "nome_municipio": mun.get("nmMunicipio") or mun.get("nome", ""),
            "uf": mun.get("sgUf") or mun.get("uf", ""),
            "valor_pago": float(valor_pago),
            "valor_empenhado": float(valor_total),
            "nr_instrumento": str(raw.get("nrConvenio") or raw.get("numero", "")),
            "tipo_instrumento": "RP6_individual",
            "numero_emenda": numero_emenda,
            "objeto": raw.get("objeto") or raw.get("dscObjeto"),
            "situacao": raw.get("situacao"),
            "data_inicio": raw.get("dtInicioVigencia"),
            "data_fim": raw.get("dtFimVigencia"),
            "confianca": 1.0,
            "fonte": "transferegov_convenio",
        }

    async def close(self):
        """Fecha o cliente HTTP."""
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
