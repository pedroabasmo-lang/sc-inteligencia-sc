"""Schemas Pydantic v2 para todas as entidades do sistema sc-inteligencia."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ======================================================================= #
# Enums                                                                     #
# ======================================================================= #

class CasaLegislativa(str, Enum):
    CAMARA = "cd"
    SENADO = "sf"
    ALESC = "alesc"


class TipoRP(str, Enum):
    RP6_INDIVIDUAL = "RP6_individual"
    RPE_TRANSFERENCIA = "RPE_transferencia_especial"
    RP7_BANCADA = "RP7_bancada"
    RP8_COMISSAO = "RP8_comissao"
    RP9_RELATOR = "RP9_relator"
    DESCONHECIDO = "desconhecido"


class TipoMatch(str, Enum):
    EXATO = "exato"
    FUZZY = "fuzzy"
    INFERIDO = "inferido"
    MANUAL = "manual"
    NAO_RESOLVIDO = "nao_resolvido"


class CategoriaTriangulacao(str, Enum):
    OPORTUNIDADE_OURO = "OPORTUNIDADE-OURO"
    OPORTUNIDADE_MEDIA = "OPORTUNIDADE-MEDIA"
    ALIADO_FIEL = "ALIADO-FIEL"
    NEUTRO = "NEUTRO"
    ADVERSARIO = "ADVERSARIO"


# ======================================================================= #
# Dimensões                                                                 #
# ======================================================================= #

class Municipio(BaseModel):
    cod_ibge: int = Field(..., description="Código IBGE 7 dígitos")
    nome: str
    nome_normalizado: str
    uf: str = Field(..., max_length=2)
    cod_uf: int
    regiao: str
    mesorregiao: Optional[str] = None
    microrregiao: Optional[str] = None
    populacao_2022: Optional[int] = None
    eleitorado_2022: Optional[int] = None
    eleitorado_2024: Optional[int] = None
    pib_municipal: Optional[Decimal] = None
    idhm: Optional[float] = None
    area_km2: Optional[float] = None
    centroide_lat: Optional[float] = None
    centroide_lng: Optional[float] = None
    cnpj_prefeitura: Optional[str] = None

    @field_validator("cod_ibge")
    @classmethod
    def valida_ibge(cls, v: int) -> int:
        if not (1_000_000 <= v <= 9_999_999):
            raise ValueError(f"Código IBGE inválido: {v}")
        return v

    @field_validator("uf")
    @classmethod
    def valida_uf(cls, v: str) -> str:
        return v.upper()


class Parlamentar(BaseModel):
    id: str  # ex: "cd_204563"
    casa: CasaLegislativa
    nome_completo: str
    nome_urna: str
    partido_atual: str
    uf: str = Field(..., max_length=2)
    legislatura: int
    id_camara: Optional[int] = None
    id_senado: Optional[int] = None
    id_alesc: Optional[int] = None
    id_tse_2022: Optional[int] = None
    foto_url: Optional[str] = None


class MandatoExecutivo(BaseModel):
    cod_ibge: int
    cargo: Literal["prefeito", "vice_prefeito"]
    nome: str
    partido_sigla: str
    coligacao: Optional[str] = None
    ano_eleicao: int
    mandato_inicio: date
    mandato_fim: date


class Partido(BaseModel):
    numero: int
    sigla_atual: str
    nome_completo: str
    federacao: Optional[str] = None
    espectro: Optional[Literal["esquerda", "centro-esquerda", "centro", "centro-direita", "direita"]] = None


# ======================================================================= #
# Fatos                                                                     #
# ======================================================================= #

class FatoVoto(BaseModel):
    cod_ibge: int
    id_candidato_tse: Optional[int] = None
    id_parlamentar: Optional[str] = None
    ano: int
    turno: int
    cargo: str
    votos: int
    percentual_validos: Optional[float] = None


class FatoEmenda(BaseModel):
    ano: int
    numero_emenda: str
    id_parlamentar_autor: Optional[str] = None
    id_bancada: Optional[str] = None
    id_comissao: Optional[str] = None
    tipo_rp: TipoRP = TipoRP.DESCONHECIDO
    esfera: str = "federal"
    cod_ibge_destino: Optional[int] = None
    uf_destino: Optional[str] = None
    funcao: Optional[str] = None
    subfuncao: Optional[str] = None
    acao_orcamentaria: Optional[str] = None
    natureza_despesa: Optional[str] = None
    objeto_resumido: Optional[str] = None
    favorecido_nome: Optional[str] = None
    favorecido_cnpj: Optional[str] = None
    instrumento_repasse: Optional[str] = None
    nr_instrumento: Optional[str] = None
    valor_autorizado: Decimal = Decimal("0")
    valor_empenhado: Decimal = Decimal("0")
    valor_liquidado: Decimal = Decimal("0")
    valor_pago: Decimal = Decimal("0")
    valor_rp_inscrito: Decimal = Decimal("0")
    impedimento_tecnico: bool = False
    data_empenho: Optional[date] = None
    data_pagamento: Optional[date] = None
    portaria_dou: Optional[str] = None
    granularidade_perdida: bool = False
    confianca_match: float = Field(default=1.0, ge=0.0, le=1.0)
    rota_match: Optional[str] = None
    fontes: list[str] = Field(default_factory=list)
    rp9_inconstitucional: bool = False

    @model_validator(mode="after")
    def marca_rp9(self) -> "FatoEmenda":
        if self.tipo_rp == TipoRP.RP9_RELATOR:
            self.rp9_inconstitucional = True
        return self

    @property
    def taxa_efetividade(self) -> float:
        if self.valor_empenhado == 0:
            return 0.0
        return float(self.valor_pago / self.valor_empenhado)


class FatoRepasseObrigatorio(BaseModel):
    cod_ibge: int
    programa: Literal["pbf", "fpm", "fundeb", "sus_piso", "pnae", "pdde", "pnate", "cide"]
    competencia: str  # "YYYY-MM"
    valor_repasse: Decimal
    beneficiarios: Optional[int] = None
    fonte: str

    @field_validator("competencia")
    @classmethod
    def valida_competencia(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}", v):
            raise ValueError(f"competencia deve ser YYYY-MM, recebido: {v!r}")
        return v


class FatoReceitaMunicipal(BaseModel):
    cod_ibge: int
    ano: int
    receita_corrente_liquida: Optional[Decimal] = None
    receita_propria: Optional[Decimal] = None
    receita_transferencia: Optional[Decimal] = None
    fonte: str = "SICONFI-DCA"


# ======================================================================= #
# Metadados                                                                 #
# ======================================================================= #

class MatchLog(BaseModel):
    origem_fonte: str
    origem_registro: str
    destino_fonte: str
    destino_registro: str
    chave_usada: str
    tipo_match: TipoMatch
    confianca: float = Field(..., ge=0.0, le=1.0)
    revisado_humano: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    observacao: Optional[str] = None


# ======================================================================= #
# Saída JSON por município (contrato front-end)                             #
# ======================================================================= #

class ScoreTriangulacao(BaseModel):
    categoria: CategoriaTriangulacao
    score_numerico: float = Field(..., ge=0.0, le=1.0)
    cartao_argumento_markdown: str


class EmendaResumo(BaseModel):
    numero: str
    ano: int
    rp: TipoRP
    funcao: Optional[str]
    objeto: Optional[str]
    empenhado: Decimal
    pago: Decimal
    efetividade: float


class ParlamentarEmendas(BaseModel):
    id: str
    nome: str
    partido: str
    cargo: str
    empenhado: Decimal
    pago: Decimal
    efetividade: float
    emendas: list[EmendaResumo] = Field(default_factory=list)


class GranularidadePerdida(BaseModel):
    uf_multiplo_valor: Decimal
    descricao: str = "Emendas com destino UF/Múltiplo ainda não conciliadas"


class MunicipioJSON(BaseModel):
    """Contrato completo do JSON de saída por município (seção 11 do prompt)."""

    cod_ibge: int
    nome: str
    uf: str
    populacao_2022: Optional[int]
    eleitorado_2022: Optional[int]
    idhm: Optional[float]
    centroide: Optional[dict]
    executivo_atual: Optional[dict]
    votacao_2022: Optional[dict]
    emendas_recebidas: Optional[dict]
    repasses_obrigatorios_12m: Optional[dict]
    receita_municipal: Optional[dict]
    score_triangulacao: Optional[ScoreTriangulacao]
    meta: dict
