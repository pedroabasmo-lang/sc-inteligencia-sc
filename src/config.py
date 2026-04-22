"""
Configurações globais do sistema sc-inteligencia.

Carrega variáveis de ambiente via pydantic-settings.
Todas as URLs base de APIs externas são definidas aqui.

Variáveis de ambiente suportadas (via .env ou ambiente):
  PORTAL_TRANSPARENCIA_API_KEY  — obrigatória para Portal da Transparência
  TRANSFEREGOV_TOKEN            — opcional, amplia dados retornados pelo TransfereGov
  LOG_LEVEL                     — nível de log (default: INFO)
  DATA_DIR                      — diretório de dados (default: ./data)
  LOOKUPS_DIR                   — diretório de lookups (default: ./lookups)
"""
import os
from pathlib import Path
from typing import Optional

try:
    from pydantic_settings import BaseSettings
    from pydantic import Field

    class Settings(BaseSettings):
        """
        Configurações do sistema sc-inteligencia.

        Lidas de variáveis de ambiente ou arquivo .env na raiz do projeto.
        """

        # ------------------------------------------------------------------ #
        # URLs base das APIs externas                                         #
        # ------------------------------------------------------------------ #
        CAMARA_API: str = "https://dadosabertos.camara.leg.br/api/v2"
        """API pública da Câmara dos Deputados — sem autenticação."""

        TRANSFEREGOV_API: str = "https://api.transferegov.gestao.gov.br"
        """API TransfereGov — convênios, transferências especiais e TEDs."""

        TRANSFEREGOV_POSTGREST_API: str = "https://api.transferegov.gestao.gov.br/transferenciasespeciais"
        """API PostgREST TransfereGov — endpoint /plano_acao_especial com filtros PostgREST."""
        # Documentação: https://docs.api.transferegov.gestao.gov.br/transferencias-especiais/

        TRANSPARENCIA_API: str = "https://api.portaldatransparencia.gov.br/api-de-dados"
        """Portal da Transparência — emendas, despesas, contratos."""

        IBGE_API: str = "https://servicodados.ibge.gov.br/api/v1"
        """IBGE Serviço de Dados v1 — localidades, estados, municípios."""

        IBGE_API_V3: str = "https://servicodados.ibge.gov.br/api/v3"
        """IBGE Serviço de Dados v3 — SIDRA (indicadores municipais, população)."""

        FNS_API: str = "https://apifns.saude.gov.br/v1/gestor"
        """Fundo Nacional de Saúde — repasses fundo-a-fundo."""

        TSE_CDN: str = "https://cdn.tse.jus.br/estatistica/sead/odsele"
        """TSE CDN — arquivos CSV/ZIP com dados eleitorais."""

        SICONFI_API: str = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
        """SICONFI/STN — demonstrativos fiscais municipais (RREO, RGF)."""

        MDS_API: str = "https://aplicacoes.mds.gov.br/sagi/servicos"
        """MDS/SAGI — indicadores sociais e programas de transferência de renda."""

        STN_API: str = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
        """STN Data Lake — Tesouro Nacional (alias de SICONFI_API)."""

        # ------------------------------------------------------------------ #
        # Credenciais / tokens (opcionais)                                    #
        # ------------------------------------------------------------------ #
        PORTAL_TRANSPARENCIA_API_KEY: Optional[str] = Field(
            default=None,
            description="Chave da API do Portal da Transparência. "
                        "Solicitar em https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email",
        )

        TRANSFEREGOV_TOKEN: Optional[str] = Field(
            default=None,
            description="Bearer token TransfereGov — opcional, amplia dados retornados.",
        )

        # ------------------------------------------------------------------ #
        # Configurações de runtime                                            #
        # ------------------------------------------------------------------ #
        LOG_LEVEL: str = "INFO"
        DATA_DIR: Path = Path("data")
        LOOKUPS_DIR: Path = Path("lookups")
        STATE_FILE: Path = Path("data/state.json")

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            case_sensitive = True

except ImportError:
    # Fallback sem pydantic-settings — usa dataclass simples com os.getenv
    class Settings:  # type: ignore[no-redef]
        """Fallback de configurações sem pydantic-settings."""

        CAMARA_API: str = "https://dadosabertos.camara.leg.br/api/v2"
        TRANSFEREGOV_API: str = "https://api.transferegov.gestao.gov.br"
        TRANSFEREGOV_POSTGREST_API: str = "https://api.transferegov.gestao.gov.br/transferenciasespeciais"
        TRANSPARENCIA_API: str = "https://api.portaldatransparencia.gov.br/api-de-dados"
        IBGE_API: str = "https://servicodados.ibge.gov.br/api/v1"
        IBGE_API_V3: str = "https://servicodados.ibge.gov.br/api/v3"
        FNS_API: str = "https://apifns.saude.gov.br/v1/gestor"
        TSE_CDN: str = "https://cdn.tse.jus.br/estatistica/sead/odsele"
        SICONFI_API: str = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
        MDS_API: str = "https://aplicacoes.mds.gov.br/sagi/servicos"
        STN_API: str = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"

        PORTAL_TRANSPARENCIA_API_KEY: Optional[str] = os.getenv("PORTAL_TRANSPARENCIA_API_KEY")
        TRANSFEREGOV_TOKEN: Optional[str] = os.getenv("TRANSFEREGOV_TOKEN")

        LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
        DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))
        LOOKUPS_DIR: Path = Path(os.getenv("LOOKUPS_DIR", "lookups"))
        STATE_FILE: Path = Path(os.getenv("STATE_FILE", "data/state.json"))

        def __init__(self):
            # Re-lê do ambiente em runtime para suportar testes que setam vars
            self.PORTAL_TRANSPARENCIA_API_KEY = os.getenv("PORTAL_TRANSPARENCIA_API_KEY")
            self.TRANSFEREGOV_TOKEN = os.getenv("TRANSFEREGOV_TOKEN")
            self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
"""Instância global de configurações — importar via ``from src.config import settings``."""
