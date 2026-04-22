"""
Normalizador canônico de municípios com fuzzy matching.

Problema: diferentes bases usam diferentes grafias para o mesmo município.
  - TSE: "SAO JOSE" / IBGE: "São José" / Portal: "São José dos Campos"
  - Solução: normalizar para ASCII uppercase, manter lookup canônico IBGE

Chaves de matching (em ordem de prioridade):
  1. cod_ibge exato (7 dígitos) — confiança 1.0
  2. nome_normalizado + uf exato — confiança 0.95
  3. rapidfuzz token_sort_ratio > 90 + uf — confiança score/100
  4. rapidfuzz token_sort_ratio > 80 + uf — confiança score/100, flag para revisão
"""
import re
import logging
from pathlib import Path
from typing import Optional
import pandas as pd
from unidecode import unidecode
from rapidfuzz import fuzz, process

logger = logging.getLogger("sc_inteligencia.normalizers.municipio")

LOOKUP_PATH = Path("lookups/municipios_br.csv")

class MunicipioNormalizer:
    """
    Lookup canônico de municípios brasileiros com fuzzy matching.
    
    Uso:
        normalizer = MunicipioNormalizer()
        await normalizer.carregar()
        
        # Match exato por IBGE
        mun = normalizer.por_ibge(4217204)
        
        # Match por nome
        resultado = normalizer.match_nome("SAO JOSE", "SC")
        # → {"cod_ibge": 4216602, "nome": "São José", "confianca": 0.95, "tipo_match": "exato"}
    """
    
    def __init__(self, lookup_path: Path = LOOKUP_PATH):
        self.lookup_path = lookup_path
        self._df: Optional[pd.DataFrame] = None
        self._by_ibge: dict[int, dict] = {}
        self._by_nome_uf: dict[str, dict] = {}
        self._nomes_por_uf: dict[str, list[str]] = {}
    
    def carregar(self, df: Optional[pd.DataFrame] = None):
        """
        Carrega lookup de municípios.
        Se df for None, lê do CSV em lookup_path.
        """
        if df is not None:
            self._df = df
        elif self.lookup_path.exists():
            self._df = pd.read_csv(self.lookup_path, dtype={"cod_ibge": int})
        else:
            raise FileNotFoundError(
                f"Lookup não encontrado: {self.lookup_path}. "
                "Execute scripts/bootstrap.py primeiro."
            )
        
        self._indexar()
        logger.info(f"Normalizer: {len(self._df)} municípios indexados")
    
    def _indexar(self):
        """Constrói índices para busca rápida."""
        for _, row in self._df.iterrows():
            cod = int(row["cod_ibge"])
            nome_norm = self._normalizar(str(row["nome"]))
            uf = str(row.get("uf", "")).upper()
            
            mun = row.to_dict()
            mun["nome_normalizado"] = nome_norm
            
            self._by_ibge[cod] = mun
            self._by_nome_uf[f"{nome_norm}_{uf}"] = mun
            
            if uf not in self._nomes_por_uf:
                self._nomes_por_uf[uf] = []
            self._nomes_por_uf[uf].append(nome_norm)
    
    def por_ibge(self, cod_ibge: int) -> Optional[dict]:
        """Retorna município por código IBGE exato. Retorna None se não encontrar."""
        # Aceita código com 6 ou 7 dígitos
        if cod_ibge < 1000000:
            # Busca por prefixo de 6 dígitos
            for k, v in self._by_ibge.items():
                if str(k)[:6] == str(cod_ibge):
                    return {**v, "confianca": 1.0, "tipo_match": "exato"}
            return None
        return {**self._by_ibge[cod_ibge], "confianca": 1.0, "tipo_match": "exato"} \
               if cod_ibge in self._by_ibge else None
    
    def match_nome(
        self,
        nome: str,
        uf: str,
        threshold_alto: float = 90.0,
        threshold_baixo: float = 80.0,
    ) -> Optional[dict]:
        """
        Match de nome de município com fuzzy matching.
        
        Returns:
            dict com cod_ibge, nome, confianca, tipo_match
            None se não encontrar acima do threshold
        """
        if self._df is None:
            raise RuntimeError("Normalizer não carregado. Chame carregar() primeiro.")
        
        uf = uf.upper().strip()
        nome_norm = self._normalizar(nome)
        
        # 1. Match exato normalizado
        chave = f"{nome_norm}_{uf}"
        if chave in self._by_nome_uf:
            mun = self._by_nome_uf[chave]
            return {"cod_ibge": mun["cod_ibge"], "nome": mun["nome"],
                    "confianca": 0.95, "tipo_match": "exato"}
        
        # 2. Fuzzy matching restrito à UF
        candidatos = self._nomes_por_uf.get(uf, [])
        if not candidatos:
            logger.warning(f"Nenhum município para UF={uf}")
            return None
        
        resultado = process.extractOne(
            nome_norm,
            candidatos,
            scorer=fuzz.token_sort_ratio,
        )
        
        if resultado is None:
            return None
        
        melhor_nome, score, _ = resultado
        confianca = score / 100.0
        
        if score >= threshold_alto:
            chave_match = f"{melhor_nome}_{uf}"
            mun = self._by_nome_uf.get(chave_match)
            if mun:
                tipo = "exato" if score == 100 else "fuzzy"
                return {
                    "cod_ibge": int(mun["cod_ibge"]),
                    "nome": mun["nome"],
                    "nome_query": nome,
                    "confianca": confianca,
                    "tipo_match": tipo,
                }
        
        if score >= threshold_baixo:
            chave_match = f"{melhor_nome}_{uf}"
            mun = self._by_nome_uf.get(chave_match)
            if mun:
                return {
                    "cod_ibge": int(mun["cod_ibge"]),
                    "nome": mun["nome"],
                    "nome_query": nome,
                    "confianca": confianca,
                    "tipo_match": "fuzzy",
                    "requer_revisao": True,
                }
        
        logger.debug(f"Sem match para '{nome}' (UF={uf}) — melhor: '{melhor_nome}' score={score:.0f}")
        return None
    
    @staticmethod
    def _normalizar(nome: str) -> str:
        """ASCII uppercase sem pontuação para comparação canônica."""
        return re.sub(r"[^A-Z0-9 ]", "", unidecode(nome).upper()).strip()
    
    def listar_uf(self, uf: str) -> list[dict]:
        """Lista todos os municípios de uma UF."""
        if self._df is None:
            return []
        subset = self._df[self._df["uf"] == uf.upper()]
        return subset.to_dict("records")


# Singleton global
_normalizer: Optional[MunicipioNormalizer] = None

def get_normalizer() -> MunicipioNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = MunicipioNormalizer()
        _normalizer.carregar()
    return _normalizer
