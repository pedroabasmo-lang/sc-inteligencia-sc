"""
Coletores de dados externos do sc-inteligencia.

Módulos disponíveis:
  ibge          — Localidades e indicadores municipais (IBGE API v1/v3)
  camara        — Deputados federais (API Câmara dos Deputados v2)
  transferegov  — Transferências especiais e convênios (TransfereGov API)
  fns           — Repasses fundo-a-fundo do SUS (FNS API)
  transparencia — Emendas parlamentares (Portal da Transparência API)
"""
from src.collectors.ibge import IBGECollector
from src.collectors.camara import CamaraCollector
from src.collectors.transferegov import TransfereGovCollector
from src.collectors.fns import FNSCollector
from src.collectors.transparencia import TransparenciaCollector

__all__ = [
    "IBGECollector",
    "CamaraCollector",
    "TransfereGovCollector",
    "FNSCollector",
    "TransparenciaCollector",
]
