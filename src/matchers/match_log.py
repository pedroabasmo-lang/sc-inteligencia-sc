"""Registro auditável de decisões de match emenda↔município."""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from src.config import settings

logger = logging.getLogger("sc_inteligencia.matchers.match_log")

SCHEMA = pa.schema([
    pa.field("origem_fonte", pa.string()),
    pa.field("origem_registro", pa.string()),
    pa.field("destino_fonte", pa.string()),
    pa.field("destino_registro", pa.string()),
    pa.field("chave_usada", pa.string()),
    pa.field("tipo_match", pa.string()),  # exato|fuzzy|inferido|manual|nao_resolvido
    pa.field("confianca", pa.float32()),
    pa.field("revisado_humano", pa.bool_()),
    pa.field("timestamp", pa.timestamp("us")),
    pa.field("numero_emenda", pa.string()),
    pa.field("cod_ibge", pa.int64()),
    pa.field("observacao", pa.string()),
])

class MatchLogger:
    """
    Registra cada decisão de match emenda↔município em match_log.parquet.
    Garante rastreabilidade completa conforme especificação do projeto.
    
    Todo FatoEmenda com cod_ibge_destino deve ter linha correspondente aqui.
    """
    
    def __init__(self, path: Optional[Path] = None):
        self.path = path or Path(settings.MATCH_LOG_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._buffer: list[dict] = []
        self._flush_threshold = 100
    
    def registrar(
        self,
        numero_emenda: str,
        cod_ibge: Optional[int],
        origem_fonte: str,
        chave_usada: str,
        tipo_match: str,
        confianca: float,
        origem_registro: str = "",
        destino_fonte: str = "ibge_municipios",
        destino_registro: str = "",
        observacao: str = "",
    ):
        """Registra uma decisão de match."""
        self._buffer.append({
            "origem_fonte": origem_fonte,
            "origem_registro": origem_registro,
            "destino_fonte": destino_fonte,
            "destino_registro": destino_registro or str(cod_ibge or ""),
            "chave_usada": chave_usada,
            "tipo_match": tipo_match,
            "confianca": float(confianca),
            "revisado_humano": False,
            "timestamp": datetime.utcnow(),
            "numero_emenda": numero_emenda,
            "cod_ibge": int(cod_ibge) if cod_ibge else -1,
            "observacao": observacao,
        })
        if len(self._buffer) >= self._flush_threshold:
            self.flush()
    
    def registrar_nao_resolvido(self, numero_emenda: str, origem_fonte: str, motivo: str):
        """Registra emenda que não pôde ser resolvida para nenhum município."""
        self.registrar(
            numero_emenda=numero_emenda,
            cod_ibge=None,
            origem_fonte=origem_fonte,
            chave_usada="nenhuma",
            tipo_match="nao_resolvido",
            confianca=0.0,
            observacao=motivo,
        )
    
    def flush(self):
        """Persiste buffer em Parquet (append)."""
        if not self._buffer:
            return
        
        df = pd.DataFrame(self._buffer)
        table = pa.Table.from_pandas(df, schema=SCHEMA, safe=False)
        
        if self.path.exists():
            existing = pq.read_table(self.path)
            combined = pa.concat_tables([existing, table])
            pq.write_table(combined, self.path, compression="snappy")
        else:
            pq.write_table(table, self.path, compression="snappy")
        
        logger.debug(f"MatchLog: {len(self._buffer)} registros persistidos")
        self._buffer = []
    
    def ler(self) -> pd.DataFrame:
        """Lê o log completo como DataFrame."""
        if not self.path.exists():
            return pd.DataFrame(columns=[f.name for f in SCHEMA])
        return pq.read_table(self.path).to_pandas()
    
    def __del__(self):
        """Garante flush ao destruir objeto."""
        try:
            self.flush()
        except Exception:
            pass
