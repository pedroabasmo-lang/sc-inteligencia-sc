# src/utils/http.py
"""Cliente HTTP assíncrono com retry exponencial, rate limiting por domínio
e suporte a paginação automática.
"""
import asyncio
import logging
from typing import Any, AsyncGenerator, Optional
from urllib.parse import urlparse

import httpx
from rich.logging import RichHandler
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logging.basicConfig(handlers=[RichHandler()], level=logging.INFO)
logger = logging.getLogger("sc_inteligencia.http")

# Registro global de semáforos por domínio
_semaphores: dict[str, asyncio.Semaphore] = {}


def get_semaphore(domain: str, limit: int = 5) -> asyncio.Semaphore:
    """Retorna (criando se necessário) o semáforo de concorrência para o domínio."""
    if domain not in _semaphores:
        _semaphores[domain] = asyncio.Semaphore(limit)
    return _semaphores[domain]


class APIClient:
    """Cliente HTTP assíncrono reutilizável.

    Parâmetros
    ----------
    base_url:
        URL raiz da API (ex.: ``"https://dadosabertos.camara.leg.br/api/v2"``).
    headers:
        Cabeçalhos padrão enviados em todas as requisições.
        Use ``{"Authorization": "Bearer <token>"}`` ou
        ``{"chave-api-dados": "<key>"}`` conforme a API alvo.
    rate_limit:
        Máximo de requisições simultâneas ao mesmo domínio.
    timeout:
        Timeout em segundos para requisições GET (padrão 30 s).
    """

    def __init__(
        self,
        base_url: str,
        headers: Optional[dict[str, str]] = None,
        rate_limit: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self.domain = urlparse(base_url).netloc
        self.semaphore = get_semaphore(self.domain, rate_limit)

    # ------------------------------------------------------------------ #
    # Helpers internos                                                     #
    # ------------------------------------------------------------------ #

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _merged_headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        return {**self.headers, **(extra or {})}

    async def _handle_429(self, resp: httpx.Response) -> None:
        """Aguarda o tempo indicado pelo header ``Retry-After`` e relança."""
        retry_after = int(resp.headers.get("Retry-After", "60"))
        logger.warning("Rate limit em %s, aguardando %ds", resp.url, retry_after)
        await asyncio.sleep(retry_after)
        raise httpx.HTTPStatusError(
            message="429 Too Many Requests",
            request=resp.request,
            response=resp,
        )

    # ------------------------------------------------------------------ #
    # Métodos públicos                                                     #
    # ------------------------------------------------------------------ #

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def get_json(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> Any:
        """Executa GET e retorna o corpo JSON deserializado.

        Parâmetros
        ----------
        path:
            Caminho relativo ao ``base_url``.
        params:
            Query-string parameters.
        extra_headers:
            Cabeçalhos adicionais mesclados aos padrão para esta chamada.
        """
        url = self._build_url(path)
        headers = self._merged_headers(extra_headers)
        async with self.semaphore:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 429:
                    await self._handle_429(resp)
                resp.raise_for_status()
                return resp.json()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def get_bytes(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> bytes:
        """Executa GET e retorna o corpo bruto em bytes (útil para CSV/ZIP)."""
        url = self._build_url(path)
        async with self.semaphore:
            # Timeout maior para downloads de arquivos grandes
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(url, params=params, headers=self.headers)
                if resp.status_code == 429:
                    await self._handle_429(resp)
                resp.raise_for_status()
                return resp.content

    async def get_paginated(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        page_param: str = "pagina",
        items_key: Optional[str] = None,
        page_size: int = 100,
    ) -> AsyncGenerator[list[Any], None]:
        """Gerador assíncrono que itera sobre todas as páginas de um endpoint.

        Parâmetros
        ----------
        path:
            Caminho relativo ao ``base_url``.
        params:
            Parâmetros fixos enviados em todas as páginas.
        page_param:
            Nome do query-param de paginação (padrão ``"pagina"``).
        items_key:
            Chave do dict de resposta que contém a lista de itens.
            Se ``None``, assume que a resposta já é uma lista ou usa ``"dados"``.
        page_size:
            Quantidade de itens por página (enviada como ``itens``).

        Yields
        ------
        list[Any]
            Lista de itens de cada página.
        """
        params = dict(params or {})
        params["itens"] = page_size
        page = 1

        while True:
            params[page_param] = page
            data = await self.get_json(path, params=params)

            # Normaliza a resposta para uma lista
            if isinstance(data, list):
                items: list[Any] = data
            elif isinstance(data, dict):
                if items_key and items_key in data:
                    items = data[items_key]
                else:
                    items = data.get("dados", [])
            else:
                items = []

            if not items:
                break

            yield items

            if len(items) < page_size:
                # Última página (parcial) — encerra iteração
                break

            page += 1
