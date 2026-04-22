"""
Coletor IBGE — Localidades e indicadores municipais.

URL base: https://servicodados.ibge.gov.br/api/v1 (v1) e /api/v3 (v3 SIDRA)

Endpoints usados:
  - GET /localidades/municipios?orderBy=nome  → lista todos os 5570 municípios (sem autenticação)
  - GET /localidades/estados/{uf}/municipios  → municípios de uma UF
  - GET /localidades/municipios/{codigo}      → município específico
  - GET /agregados/6579/periodos/2022/variaveis/9324
      ?localidades=N6[{cod6}]                 → estimativa populacional (SIDRA tabela 6579)

Rate limit: não documentado oficialmente; usar semáforo conservador de 10 req/s (v1)
            e 5 req/s (v3 SIDRA), pois o SIDRA pode ser mais lento.
Autenticação: não requer.

Formato de resposta de /localidades/municipios (item):
{
  "id": 4200051,
  "nome": "Abdon Batista",
  "microrregiao": {
    "id": 42001,
    "nome": "Curitibanos",
    "mesorregiao": {
      "id": 4201,
      "nome": "Oeste Catarinense",
      "UF": {"id": 42, "sigla": "SC", "nome": "Santa Catarina", "regiao": {...}}
    }
  },
  "regiao-imediata": {"id": 420001, "nome": "...", "regiao-intermediaria": {...}}
}

Formato de resposta SIDRA /agregados/6579/periodos/2022/variaveis/9324 (item):
{
  "id": 9324,
  "variavel": "Populacao estimada",
  "unidade": "Pessoas",
  "resultados": [{
    "classificacoes": [],
    "series": [{"localidade": {"id": "420005", "nivel": {...}, "nome": "..."}, "serie": {"2022": "2735"}}]
  }]
}
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from src.utils.http import APIClient
from src.config import settings

logger = logging.getLogger("sc_inteligencia.collectors.ibge")

IBGE_REGIOES: dict[str, list[str]] = {
    "Norte":       ["AC", "AM", "AP", "PA", "RO", "RR", "TO"],
    "Nordeste":    ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste":["DF", "GO", "MS", "MT"],
    "Sudeste":     ["ES", "MG", "RJ", "SP"],
    "Sul":         ["PR", "RS", "SC"],
}

UF_CODIGOS: dict[str, int] = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17,
    "MA": 21, "PI": 22, "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27,
    "SE": 28, "BA": 29,
    "MG": 31, "ES": 32, "RJ": 33, "SP": 35,
    "PR": 41, "SC": 42, "RS": 43,
    "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}


class IBGECollector:
    """
    Coleta e normaliza dados de municípios do IBGE.

    Endpoints consumidos:
      - /localidades/municipios         (API v1)
      - /localidades/estados/{uf}/municipios (API v1)
      - /localidades/municipios/{id}    (API v1)
      - /agregados/6579/periodos/2022/variaveis/9324 (API v3 SIDRA)

    Uso básico:
        async with IBGECollector() as collector:
            municipios = await collector.listar_municipios_br()
            sc = await collector.listar_municipios_uf("SC")
            pop = await collector.buscar_populacao(4205407)  # Florianópolis
    """

    def __init__(self):
        self.client_v1 = APIClient(
            base_url=settings.IBGE_API,
            rate_limit=10,
        )
        self.client_v3 = APIClient(
            base_url=settings.IBGE_API_V3,
            rate_limit=5,
        )

    async def listar_municipios_br(self) -> list[dict]:
        """
        Retorna todos os 5570 municípios brasileiros normalizados em ordem alfabética.

        Campos retornados por município:
          cod_ibge (int)        — código IBGE de 7 dígitos
          nome (str)            — nome com acentuação original
          nome_normalizado (str)— nome em maiúsculas sem acentos para matching
          uf (str)              — sigla da UF (ex: "SC")
          cod_uf (int)          — código numérico da UF
          regiao (str)          — Grande Região (Norte, Nordeste, etc.)
          mesorregiao (str)     — nome da mesorregião
          microrregiao (str)    — nome da microrregião

        Returns:
            list[dict] com 5570 itens normalizados.
        """
        logger.info("IBGE: buscando todos os municípios brasileiros...")
        raw = await self.client_v1.get_json(
            "/localidades/municipios",
            params={"orderBy": "nome"},
        )
        municipios = [self._normalizar(m) for m in raw]
        logger.info(f"IBGE: {len(municipios)} municípios obtidos")
        return municipios

    async def listar_municipios_uf(self, uf: str) -> list[dict]:
        """
        Retorna municípios de uma UF específica.

        Args:
            uf: sigla da UF em maiúsculas ou minúsculas (ex: "SC", "sc")

        Returns:
            list[dict] com municípios normalizados da UF.
        """
        uf = uf.upper()
        logger.info(f"IBGE: buscando municípios da UF {uf}...")
        raw = await self.client_v1.get_json(
            f"/localidades/estados/{uf}/municipios",
        )
        return [self._normalizar(m) for m in raw]

    async def buscar_municipio(self, cod_ibge: int) -> Optional[dict]:
        """
        Busca dados de um município específico pelo código IBGE de 7 dígitos.

        Args:
            cod_ibge: código IBGE de 7 dígitos (ex: 4205407 para Florianópolis)

        Returns:
            dict normalizado ou None se não encontrado.
        """
        try:
            raw = await self.client_v1.get_json(
                f"/localidades/municipios/{cod_ibge}",
            )
            if not raw:
                return None
            # Resposta pode ser dict ou lista com um item
            if isinstance(raw, list):
                raw = raw[0] if raw else None
            return self._normalizar(raw) if raw else None
        except Exception as e:
            logger.warning(f"IBGE: erro ao buscar município {cod_ibge}: {e}")
            return None

    async def buscar_populacao(self, cod_ibge: int) -> Optional[int]:
        """
        Busca população estimada do município via SIDRA API v3.

        Tabela 6579 — Estimativas da população residente nos municípios do Brasil
        Variável 9324 — Populacao estimada
        Período: 2022 (mais recente disponível via SIDRA)

        Args:
            cod_ibge: código IBGE de 7 dígitos

        Returns:
            Número de habitantes (int) ou None se indisponível.

        Nota:
            O SIDRA usa código de 6 dígitos (trunca o dígito verificador).
            Valores "..." indicam supressão de confidencialidade.
        """
        try:
            # SIDRA usa 6 dígitos (sem o dígito verificador do IBGE)
            cod_6 = str(cod_ibge)[:6]
            url = "/agregados/6579/periodos/2022/variaveis/9324"
            params = {
                "localidades": f"N6[{cod_6}]",
                "classificacao": "none",
            }
            data = await self.client_v3.get_json(url, params=params)

            if not data or not isinstance(data, list):
                return None

            resultados = data[0].get("resultados", [])
            if not resultados:
                return None

            series = resultados[0].get("series", [])
            if not series:
                return None

            valor = series[0].get("serie", {}).get("2022")
            if valor and valor not in ("...", "-", ""):
                # Remove separadores de milhar antes de converter
                return int(valor.replace(".", "").replace(",", "").strip())
        except Exception as e:
            logger.warning(f"IBGE SIDRA: erro ao buscar população de {cod_ibge}: {e}")
        return None

    async def buscar_populacoes_uf(self, uf: str) -> dict[int, int]:
        """
        Busca população de todos os municípios de uma UF de forma eficiente.

        Usa chamada em lote ao SIDRA (todos os municípios da UF de uma vez)
        em vez de uma chamada por município.

        Args:
            uf: sigla da UF (ex: "SC")

        Returns:
            dict mapeando cod_ibge → população
        """
        uf = uf.upper()
        cod_uf = UF_CODIGOS.get(uf)
        if not cod_uf:
            logger.warning(f"IBGE: UF desconhecida: {uf}")
            return {}

        try:
            url = "/agregados/6579/periodos/2022/variaveis/9324"
            params = {
                "localidades": f"N6[in N3[{cod_uf}]]",
                "classificacao": "none",
            }
            data = await self.client_v3.get_json(url, params=params)

            if not data or not isinstance(data, list):
                return {}

            resultado: dict[int, int] = {}
            resultados = data[0].get("resultados", [])
            for res in resultados:
                for serie_item in res.get("series", []):
                    loc_id = serie_item.get("localidade", {}).get("id", "")
                    valor = serie_item.get("serie", {}).get("2022", "")
                    if loc_id and valor and valor not in ("...", "-", ""):
                        try:
                            # Adiciona dígito 0 para completar 7 dígitos se necessário
                            cod = int(loc_id)
                            pop = int(valor.replace(".", "").replace(",", "").strip())
                            resultado[cod] = pop
                        except (ValueError, TypeError):
                            pass
            logger.info(f"IBGE SIDRA: {len(resultado)} populações obtidas para {uf}")
            return resultado
        except Exception as e:
            logger.warning(f"IBGE SIDRA: erro ao buscar populações de {uf}: {e}")
            return {}

    def _normalizar(self, raw: dict) -> dict:
        """
        Normaliza resposta bruta da API IBGE para schema canônico.

        A estrutura aninhada da resposta IBGE é achatada em campos diretos.
        A hierarquia é: microrregiao → mesorregiao → UF → regiao.
        """
        micro = raw.get("microrregiao") or {}
        meso = micro.get("mesorregiao") or raw.get("mesorregiao") or {}
        estado = meso.get("UF") or {}

        uf_sigla = estado.get("sigla", "")
        cod_uf = estado.get("id", UF_CODIGOS.get(uf_sigla, 0))

        regiao = "Desconhecida"
        for r, ufs in IBGE_REGIOES.items():
            if uf_sigla in ufs:
                regiao = r
                break

        return {
            "cod_ibge": raw["id"],
            "nome": raw["nome"],
            "nome_normalizado": self._norm_nome(raw["nome"]),
            "uf": uf_sigla,
            "cod_uf": cod_uf,
            "regiao": regiao,
            "mesorregiao": meso.get("nome"),
            "microrregiao": micro.get("nome"),
        }

    @staticmethod
    def _norm_nome(nome: str) -> str:
        """
        Normaliza nome de município para matching fuzzy.

        Converte para maiúsculas, remove acentos, remove pontuação especial.
        Exemplos:
          "Balneário Camboriú" → "BALNEARIO CAMBORIU"
          "São Miguel d'Oeste" → "SAO MIGUEL D OESTE"
        """
        try:
            from unidecode import unidecode
            sem_acento = unidecode(nome)
        except ImportError:
            # Fallback sem unidecode: remoção básica de acentos
            import unicodedata
            sem_acento = "".join(
                c for c in unicodedata.normalize("NFD", nome)
                if unicodedata.category(c) != "Mn"
            )
        return re.sub(r"[^A-Z0-9 ]", "", sem_acento.upper()).strip()

    async def salvar_lookup(
        self,
        path: Path = Path("lookups/municipios_br.csv"),
    ):
        """
        Salva CSV canônico de municípios para uso offline.

        Arquivo gerado inclui todos os campos normalizados + nome_normalizado
        para matching fuzzy. Útil para enriquecer dados sem chamadas repetidas à API.

        Args:
            path: caminho do arquivo CSV de saída

        Returns:
            pandas.DataFrame com os dados salvos.
        """
        try:
            import pandas as pd
        except ImportError as e:
            raise ImportError("pandas necessário para salvar_lookup. pip install pandas") from e

        municipios = await self.listar_municipios_br()
        df = pd.DataFrame(municipios)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        logger.info(f"IBGE: lookup salvo em {path} ({len(df)} municípios)")
        return df

    async def close(self):
        """Fecha clientes HTTP. Chamar ao encerrar o coletor."""
        await self.client_v1.close()
        await self.client_v3.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
