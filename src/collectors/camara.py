"""
Coletor API Câmara dos Deputados v2.

URL base: https://dadosabertos.camara.leg.br/api/v2
Documentação: https://dadosabertos.camara.leg.br/swagger-ui

Endpoints usados:
  GET /deputados
      Params: idLegislatura, siglaUF, siglaPartido, itens, pagina
      → Lista paginada de deputados em exercício.
      Rate limit: ~5 req/s (sem autenticação)

  GET /deputados/{id}
      → Perfil completo com gabinete, CPF, situação atual.
      Resposta encapsulada em {"dados": {...}, "links": [...]}

  GET /deputados/{id}/mandatos
      → Histórico completo de mandatos do parlamentar.

  GET /deputados/{id}/despesas
      Params: ano, mes, itens, pagina
      → Cota para Exercício da Atividade Parlamentar (CEAP).
      Registro de gastos com passagens, alimentação, combustível, etc.

  GET /deputados/{id}/discursos
      Params: dataInicio, dataFim, itens, pagina
      → Discursos pronunciados em plenário.

  GET /proposicoes
      Params: idAutor, dataInicio, dataFim, codTema, itens, pagina
      → Proposições legislativas (PL, PEC, MP, etc.)

Rate limit: ~5 req/s; sem autenticação necessária.
Autenticação: não requer (dados abertos).

Formato de resposta de /deputados (item):
{
  "id": 204563,
  "nome": "Carol de Toni",
  "siglaPartido": "PL",
  "siglaUf": "SC",
  "idLegislatura": 57,
  "urlFoto": "https://www.camara.leg.br/internet/deputado/bandep/204563.jpg",
  "email": "dep.caroldetoni@camara.leg.br"
}

Formato de resposta de /deputados/{id} (campo "dados"):
{
  "id": 204563,
  "nomeCivil": "Carolina de Toni",
  "cpf": "...",
  "ultimoStatus": {
    "id": 204563,
    "nomeEleitoral": "Carol de Toni",
    "siglaPartido": "PL",
    "siglaUf": "SC",
    "idLegislatura": 57,
    "descricaoSituacao": "Exercício",
    "gabinete": {"nome": "Carol de Toni", "predio": "4", "sala": "430", "andar": "4", "telefone": "3215-5430", "email": "..."}
  }
}

ATENÇÃO: A API da Câmara não tem endpoint direto de emendas RP6.
Para emendas RP6/RPE, usar TransparenciaCollector (Portal da Transparência)
filtrado por nomeAutor + ano. Este coletor foca em: perfis, mandatos, CEAP,
e mapeamento id_camara → nome_urna para cruzamento com outros sistemas.
"""
import logging
from typing import Optional, AsyncGenerator

from src.utils.http import APIClient
from src.config import settings

logger = logging.getLogger("sc_inteligencia.collectors.camara")

LEGISLATURA_ATUAL: int = 57  # 1º fev 2023 — 31 jan 2027

# Mapeamento de temas legislativos relevantes para sc-inteligencia
TEMAS_RELEVANTES: dict[str, int] = {
    "saude": 40,
    "educacao": 46,
    "assistencia_social": 44,
    "obras_infraestrutura": 38,
    "meio_ambiente": 41,
    "seguranca_publica": 5,
    "economia": 47,
}


class CamaraCollector:
    """
    Coleta dados de deputados federais da API Câmara dos Deputados v2.

    Importante: A identificação de emendas RP6/RPE por deputado é feita via
    Portal da Transparência (TransparenciaCollector), não diretamente pela API
    da Câmara. Este coletor entrega:
      - Lista de deputados por UF/legislatura
      - Perfis completos (gabinete, CPF, nome civil vs nome de urna)
      - Histórico de mandatos
      - Gastos com CEAP (cota parlamentar)
      - Proposições legislativas

    Uso básico:
        async with CamaraCollector() as collector:
            deps_sc = await collector.listar_deputados(uf="SC")
            perfil = await collector.perfil_deputado(204563)
            ceap = await collector.buscar_despesas_ceap(204563, ano=2024)
    """

    def __init__(self):
        self.client = APIClient(
            base_url=settings.CAMARA_API,
            rate_limit=5,
            headers={"Accept": "application/json"},
        )

    async def listar_deputados(
        self,
        uf: Optional[str] = None,
        partido: Optional[str] = None,
        legislatura: int = LEGISLATURA_ATUAL,
    ) -> list[dict]:
        """
        Lista deputados federais em exercício.

        Args:
            uf: sigla da UF para filtrar (ex: "SC") — None retorna todos.
            partido: sigla do partido (ex: "PT", "PL") — None retorna todos.
            legislatura: número da legislatura (default: 57 = 2023-2027).

        Returns:
            Lista de dicts normalizados com: id_camara, nome_completo, nome_urna,
            partido, uf, legislatura, foto_url, email.
        """
        params: dict = {"idLegislatura": legislatura, "itens": 512}
        if uf:
            params["siglaUF"] = uf.upper()
        if partido:
            params["siglaPartido"] = partido.upper()

        data = await self.client.get_json("/deputados", params=params)
        deputados_raw = data.get("dados", []) if isinstance(data, dict) else data

        result = [self._normalizar_deputado(d) for d in deputados_raw]
        logger.info(
            f"Câmara: {len(result)} deputados (uf={uf or 'BR'}, legislatura={legislatura})"
        )
        return result

    async def perfil_deputado(self, id_camara: int) -> Optional[dict]:
        """
        Busca perfil completo de um deputado pelo ID da Câmara.

        Retorna campos adicionais vs listar_deputados: CPF, nome civil,
        data de nascimento, escolaridade, e dados do gabinete físico.

        Args:
            id_camara: ID numérico do deputado no sistema da Câmara.

        Returns:
            dict normalizado com perfil completo, ou None em caso de erro.
        """
        try:
            data = await self.client.get_json(f"/deputados/{id_camara}")
            raw = data.get("dados", data) if isinstance(data, dict) else data
            return self._normalizar_perfil(raw)
        except Exception as e:
            logger.warning(f"Câmara: erro ao buscar perfil do deputado {id_camara}: {e}")
            return None

    async def listar_deputados_uf_completo(self, uf: str) -> list[dict]:
        """
        Retorna deputados de uma UF com perfil completo (inclui nome_urna e gabinete).

        Realiza N+1 chamadas (1 listagem + 1 perfil por deputado).
        Para SC tem ~16 deputados → ~17 chamadas.

        Args:
            uf: sigla da UF (ex: "SC")

        Returns:
            Lista de dicts com campos mesclados de _normalizar_deputado + _normalizar_perfil.
        """
        deps = await self.listar_deputados(uf=uf)
        perfis = []
        for d in deps:
            perfil = await self.perfil_deputado(d["id_camara"])
            if perfil:
                # Mescla perfil completo sobre dados básicos
                perfis.append({**d, **perfil})
            else:
                perfis.append(d)
        logger.info(f"Câmara: {len(perfis)} perfis completos para UF {uf}")
        return perfis

    async def buscar_mandatos(self, id_camara: int) -> list[dict]:
        """
        Busca histórico completo de mandatos de um deputado.

        Útil para identificar se o deputado é 1º, 2º, 3º mandato, etc.
        e para rastrear mudanças de partido ao longo do tempo.

        Args:
            id_camara: ID numérico do deputado.

        Returns:
            Lista de dicts com: legislatura, partido, uf, inicio, fim, situacao.
        """
        try:
            data = await self.client.get_json(f"/deputados/{id_camara}/mandatos")
            mandatos_raw = data.get("dados", []) if isinstance(data, dict) else data
            return [self._normalizar_mandato(m) for m in mandatos_raw]
        except Exception as e:
            logger.warning(f"Câmara: erro ao buscar mandatos de {id_camara}: {e}")
            return []

    async def buscar_despesas_ceap(
        self,
        id_camara: int,
        ano: int,
        mes: Optional[int] = None,
    ) -> list[dict]:
        """
        Busca despesas da Cota para Exercício da Atividade Parlamentar (CEAP).

        A CEAP cobre: passagens aéreas, combustível, hospedagem, alimentação,
        telefonia, segurança, divulgação da atividade parlamentar, etc.
        Teto mensal varia por UF (distância de Brasília).

        Args:
            id_camara: ID numérico do deputado.
            ano: ano de referência (ex: 2024).
            mes: mês específico (1-12) ou None para o ano todo.

        Returns:
            Lista de dicts com: tipo_despesa, fornecedor, cnpj_cpf, data,
            documento, valor, valor_reembolsado.
        """
        params: dict = {"ano": ano, "itens": 100}
        if mes:
            params["mes"] = mes

        items: list[dict] = []
        async for page in self.client.get_paginated(
            f"/deputados/{id_camara}/despesas",
            params=params,
            items_key="dados",
        ):
            items.extend(page)

        logger.debug(
            f"Câmara CEAP: {len(items)} despesas para deputado {id_camara} ({ano})"
        )
        return items

    async def buscar_proposicoes(
        self,
        id_camara: int,
        ano_inicio: Optional[int] = None,
        ano_fim: Optional[int] = None,
        cod_tema: Optional[int] = None,
    ) -> list[dict]:
        """
        Busca proposições legislativas de autoria do deputado.

        Args:
            id_camara: ID numérico do deputado.
            ano_inicio: ano inicial do período de busca.
            ano_fim: ano final do período de busca.
            cod_tema: código do tema (ver TEMAS_RELEVANTES).

        Returns:
            Lista de proposições com: numero, ementa, data, tema, situacao, url.
        """
        params: dict = {"idAutor": id_camara, "itens": 100}
        if ano_inicio:
            params["dataInicio"] = f"{ano_inicio}-01-01"
        if ano_fim:
            params["dataFim"] = f"{ano_fim}-12-31"
        if cod_tema:
            params["codTema"] = cod_tema

        items: list[dict] = []
        try:
            async for page in self.client.get_paginated(
                "/proposicoes",
                params=params,
                items_key="dados",
            ):
                items.extend(page)
        except Exception as e:
            logger.warning(f"Câmara proposicoes {id_camara}: {e}")
        return items

    async def buscar_discursos(
        self,
        id_camara: int,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None,
    ) -> list[dict]:
        """
        Busca discursos pronunciados pelo deputado em plenário.

        Args:
            id_camara: ID numérico do deputado.
            data_inicio: data inicial no formato "YYYY-MM-DD".
            data_fim: data final no formato "YYYY-MM-DD".

        Returns:
            Lista de dicts com: data, sumario, palavras_chave, fase_evento, url_texto.
        """
        params: dict = {"itens": 100}
        if data_inicio:
            params["dataInicio"] = data_inicio
        if data_fim:
            params["dataFim"] = data_fim

        items: list[dict] = []
        try:
            async for page in self.client.get_paginated(
                f"/deputados/{id_camara}/discursos",
                params=params,
                items_key="dados",
            ):
                items.extend(page)
        except Exception as e:
            logger.warning(f"Câmara discursos {id_camara}: {e}")
        return items

    async def lookup_nome_urna(self, nome_civil: str, uf: str) -> Optional[dict]:
        """
        Tenta encontrar deputado pelo nome civil + UF.

        Útil para cruzar dados do Portal da Transparência (onde o nome pode
        estar como "PEDRO UCZAI") com o ID interno da Câmara.

        Args:
            nome_civil: nome civil ou de urna do deputado.
            uf: sigla da UF.

        Returns:
            dict com id_camara e nome_urna, ou None se não encontrado.
        """
        deps = await self.listar_deputados(uf=uf)
        nome_upper = nome_civil.upper().strip()
        for d in deps:
            if nome_upper in d["nome_completo"].upper() or nome_upper in d["nome_urna"].upper():
                return d
        return None

    # ------------------------------------------------------------------ #
    # Métodos de normalização                                              #
    # ------------------------------------------------------------------ #

    def _normalizar_deputado(self, raw: dict) -> dict:
        """
        Normaliza item da lista /deputados para schema canônico.

        Campos de entrada (API): id, nome, siglaPartido, siglaUf,
        idLegislatura, urlFoto, email.
        """
        return {
            "id_camara": raw.get("id"),
            "nome_completo": raw.get("nome", ""),
            "nome_urna": raw.get("nomeEleitoral") or raw.get("nome", ""),
            "partido": raw.get("siglaPartido", ""),
            "uf": (raw.get("siglaUf") or "").upper(),
            "legislatura": raw.get("idLegislatura", LEGISLATURA_ATUAL),
            "foto_url": raw.get("urlFoto"),
            "email": raw.get("email"),
            "id": f"cd_{raw.get('id')}",  # ID canônico para cruzamento
        }

    def _normalizar_perfil(self, raw: dict) -> dict:
        """
        Normaliza resposta de /deputados/{id}.

        A resposta tem mais campos que a listagem, incluindo ultimoStatus
        aninhado com dados do gabinete físico em Brasília.
        """
        ult = raw.get("ultimoStatus") or {}
        return {
            "id_camara": raw.get("id"),
            "cpf": raw.get("cpf"),
            "nome_completo": raw.get("nomeCivil") or ult.get("nome", ""),
            "nome_urna": ult.get("nomeEleitoral") or raw.get("nomeCivil", ""),
            "partido": ult.get("siglaPartido", ""),
            "uf": (ult.get("siglaUf") or "").upper(),
            "legislatura": ult.get("idLegislatura", LEGISLATURA_ATUAL),
            "situacao": ult.get("descricaoSituacao"),
            "gabinete": ult.get("gabinete") or {},
            "data_nascimento": raw.get("dataNascimento"),
            "escolaridade": raw.get("escolaridade"),
            "municipio_nascimento": raw.get("municipioNascimento"),
            "uf_nascimento": raw.get("ufNascimento"),
            "id": f"cd_{raw.get('id')}",
        }

    def _normalizar_mandato(self, raw: dict) -> dict:
        """Normaliza item de /deputados/{id}/mandatos."""
        return {
            "legislatura": raw.get("idLegislatura"),
            "partido": raw.get("siglaPartido", ""),
            "uf": (raw.get("siglaUf") or "").upper(),
            "inicio": raw.get("dataInicio"),
            "fim": raw.get("dataFim"),
            "situacao": raw.get("descricaoSituacao"),
        }

    async def close(self):
        """Fecha o cliente HTTP."""
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
