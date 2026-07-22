"""Shared HTTP client with timeouts, retries, and user-agent."""

from __future__ import annotations

import time
from typing import Any

import httpx

from hypeagent.config.schema import HttpConfig

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class HttpClient:
    """Thin httpx wrapper with configurable timeout, retries, and user-agent."""

    def __init__(
        self,
        http_config: HttpConfig,
        user_agent: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._retry_count = http_config.retry_count
        self._timeout = httpx.Timeout(http_config.timeout_seconds)
        self._user_agent = user_agent
        self._client = client or httpx.Client(timeout=self._timeout, verify=True)

    @property
    def user_agent(self) -> str:
        return self._user_agent

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request with user-agent, timeout, and retries."""
        merged_headers = {"User-Agent": self._user_agent}
        if headers:
            merged_headers.update(headers)

        last_exc: Exception | None = None
        attempts = self._retry_count + 1
        for attempt in range(attempts):
            try:
                response = self._client.request(
                    method,
                    url,
                    headers=merged_headers,
                    timeout=self._timeout,
                    **kwargs,
                )
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    raise
                time.sleep(0.25 * (attempt + 1))
                continue

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts - 1:
                time.sleep(0.25 * (attempt + 1))
                continue

            return response

        if last_exc is not None:
            raise last_exc
        msg = "HTTP request failed without a response"
        raise RuntimeError(msg)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)
