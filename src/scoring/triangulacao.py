"""
Motor de triangulação política: votos × emendas × partido do prefeito.

Categorias:
  OPORTUNIDADE-OURO:   prefeito aliado + votos altos + emenda zero → argumento perfeito
  OPORTUNIDADE-MEDIA:  votos razoáveis + emenda abaixo da média
  ALIADO-FIEL:         prefeito aliado + emendas proporcionais aos votos
  NEUTRO:              sem sinal claro
  ADVERSARIO:          prefeito oposição + sem votos + sem emenda
"""
import logging
from decimal import Decimal
from typing import Optional

logger = logging.getLogger("sc_inteligencia.scoring.triangulacao")

# Thresholds
EMENDA_MEDIA_DEP_FEDERAL = 38_000_000 / 295  # ~R$129k por município de SC
VOTOS_ALTO = 500
VOTOS_MEDIO = 100

PARTIDOS_ALIANCA = {
    "PL": ["PL", "PP", "REPUBLICANOS", "UNION", "MDB", "PSD", "PATRIOTA"],
    "PT": ["PT", "PCdoB", "PV", "PSOL", "REDE", "SOLIDARIEDADE"],
    "UNION": ["UNION", "MDB", "PSD", "PP", "PL"],
}

class TriangulacaoEngine:
    """
    Calcula score de triangulação política por município.
    
    Entradas:
        - votos: número de votos que o candidato teve no município em 2022
        - emenda_total: total empenhado pelo deputado no município (2023-2026)
        - partido_prefeito: sigla do partido do prefeito atual
        - partido_candidato: sigla do partido do candidato
        - populacao: população do município (para normalização)
    
    Saída:
        - categoria: CategoriaTriangulacao
        - score_numerico: 0.0 a 1.0
        - cartao_argumento_markdown: texto pronto para uso em prospecção
    """
    
    def calcular(
        self,
        municipio_nome: str,
        votos: int,
        emenda_total: float,
        partido_prefeito: str,
        partido_candidato: str,
        prefeito_nome: str = "",
        populacao: int = 10000,
        eleitorado: int = 5000,
    ) -> dict:
        """Calcula triangulação para um município."""
        
        # Normaliza dados
        votos_pct = (votos / eleitorado * 100) if eleitorado > 0 else 0
        emenda_per_capita = emenda_total / populacao if populacao > 0 else 0
        eh_aliado = self._eh_aliado(partido_prefeito, partido_candidato)
        
        # Score componentes
        score_voto = min(votos_pct / 10, 1.0)  # 10% do eleitorado = score máximo
        score_emenda = 1.0 - min(emenda_total / EMENDA_MEDIA_DEP_FEDERAL, 1.0)  # 0 emenda = score 1.0 de "oportunidade"
        score_alianca = 0.8 if eh_aliado else 0.2
        
        # Score final ponderado
        score = (score_voto * 0.4) + (score_emenda * 0.35) + (score_alianca * 0.25)
        
        # Categorização
        if eh_aliado and votos >= VOTOS_ALTO and emenda_total < EMENDA_MEDIA_DEP_FEDERAL * 0.3:
            categoria = "OPORTUNIDADE-OURO"
        elif votos >= VOTOS_MEDIO and emenda_total < EMENDA_MEDIA_DEP_FEDERAL * 0.5:
            categoria = "OPORTUNIDADE-MEDIA"
        elif eh_aliado and emenda_total >= EMENDA_MEDIA_DEP_FEDERAL * 0.8:
            categoria = "ALIADO-FIEL"
        elif not eh_aliado and votos < VOTOS_MEDIO and emenda_total < 10000:
            categoria = "ADVERSARIO"
        else:
            categoria = "NEUTRO"
        
        cartao = self._gerar_cartao(
            municipio_nome, categoria, votos, votos_pct, emenda_total,
            partido_prefeito, prefeito_nome, eh_aliado
        )
        
        return {
            "categoria": categoria,
            "score_numerico": round(score, 4),
            "cartao_argumento_markdown": cartao,
            "componentes": {
                "score_voto": round(score_voto, 3),
                "score_emenda_oportunidade": round(score_emenda, 3),
                "score_alianca": round(score_alianca, 3),
            },
        }
    
    def _eh_aliado(self, partido_prefeito: str, partido_candidato: str) -> bool:
        """Verifica se prefeito é aliado do candidato (mesma federação ou coligação histórica)."""
        if partido_prefeito == partido_candidato:
            return True
        aliados = PARTIDOS_ALIANCA.get(partido_candidato, [])
        return partido_prefeito.upper() in [a.upper() for a in aliados]
    
    def _gerar_cartao(
        self,
        municipio: str,
        categoria: str,
        votos: int,
        votos_pct: float,
        emenda_total: float,
        partido_prefeito: str,
        prefeito_nome: str,
        eh_aliado: bool,
    ) -> str:
        """Gera cartão de argumento em Markdown para uso em prospecção."""
        
        emenda_str = (
            f"R$ {emenda_total:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if emenda_total >= 1000
            else "R$ 0"
        )
        
        if categoria == "OPORTUNIDADE-OURO":
            return (
                f"## 🏆 {municipio} — Oportunidade Ouro\n\n"
                f"**{votos:,} votos** ({votos_pct:.1f}% do eleitorado) em 2022, "
                f"mas apenas **{emenda_str}** em emendas nos últimos 4 anos.\n\n"
                f"O prefeito **{prefeito_nome or partido_prefeito}** ({partido_prefeito}) "
                f"é {'aliado' if eh_aliado else 'independente'}. "
                f"Este município merece e pode receber mais recursos. "
                f"**Argumento**: 'Você me deu votos, eu preciso te dar resultados.'"
            )
        elif categoria == "OPORTUNIDADE-MEDIA":
            return (
                f"## 🎯 {municipio} — Oportunidade Média\n\n"
                f"**{votos:,} votos** em 2022 com **{emenda_str}** em emendas. "
                f"Potencial de conversão com aumento de emendas direcionadas."
            )
        elif categoria == "ALIADO-FIEL":
            return (
                f"## ✅ {municipio} — Aliado Fiel\n\n"
                f"**{votos:,} votos** e **{emenda_str}** em emendas. "
                f"Prefeito aliado ({partido_prefeito}). Manter e fortalecer relação."
            )
        elif categoria == "ADVERSARIO":
            return (
                f"## ⚠️ {municipio} — Adversário\n\n"
                f"Baixa votação e sem emendas. Prefeito ({partido_prefeito}) é oposição. "
                f"Avaliar custo-benefício de investimento político."
            )
        else:
            return (
                f"## ➡️ {municipio} — Neutro\n\n"
                f"**{votos:,} votos** e **{emenda_str}** em emendas. "
                f"Sem sinal claro de oportunidade ou risco."
            )
