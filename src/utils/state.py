# src/utils/state.py
"""Controle de estado incremental — rastreia último mês ingerido por fonte."""
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.config import settings


class SyncState:
    """Persiste e consulta o estado de sincronização por fonte de dados.

    O arquivo de estado é um JSON simples com estrutura::

        {
            "<fonte>": {
                "last_month": "YYYY-MM",
                "last_run": "<ISO datetime>"
            },
            ...
        }

    Parâmetros
    ----------
    path:
        Caminho para o arquivo JSON de estado.
        Se ``None``, usa ``settings.STATE_FILE``.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or Path(settings.STATE_FILE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict = self._load()

    # ------------------------------------------------------------------ #
    # I/O                                                                  #
    # ------------------------------------------------------------------ #

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._state, indent=2, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #

    def get_last_month(self, fonte: str) -> Optional[str]:
        """Retorna ``'YYYY-MM'`` do último mês ingerido para *fonte*, ou ``None``."""
        return self._state.get(fonte, {}).get("last_month")

    def set_synced(self, fonte: str, month: str) -> None:
        """Registra a conclusão da ingestão de *month* (``'YYYY-MM'``) para *fonte*."""
        self._state[fonte] = {
            "last_month": month,
            "last_run": datetime.utcnow().isoformat(),
        }
        self._save()

    def pending_months(self, fonte: str, until: Optional[str] = None) -> list[str]:
        """Retorna lista de meses ``YYYY-MM`` pendentes de ingestão.

        A sequência começa no mês seguinte ao ``last_month`` gravado e vai
        até *until* (inclusive).  Se *last_month* for ``None``, retorna apenas
        o mês anterior ao mês corrente (comportamento conservador para uma
        primeira execução).

        Parâmetros
        ----------
        fonte:
            Identificador da fonte de dados (ex.: ``"transferegov_pbf"``).
        until:
            Mês final no formato ``YYYY-MM``.  Se ``None``, usa o mês
            imediatamente anterior ao mês atual.

        Retorna
        -------
        list[str]
            Lista ordenada de meses no formato ``YYYY-MM``.
        """
        if until is None:
            today = date.today()
            if today.month > 1:
                until = f"{today.year}-{today.month - 1:02d}"
            else:
                until = f"{today.year - 1}-12"

        last = self.get_last_month(fonte)
        if last is None:
            return [until]

        months: list[str] = []
        current = _next_month(last)
        while current <= until:
            months.append(current)
            current = _next_month(current)
        return months


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _next_month(ym: str) -> str:
    """Retorna o mês seguinte a *ym* no formato ``'YYYY-MM'``."""
    year, month = int(ym[:4]), int(ym[5:7])
    month += 1
    if month > 12:
        month, year = 1, year + 1
    return f"{year}-{month:02d}"


# Singleton — importar com: from src.utils.state import state
state = SyncState()
