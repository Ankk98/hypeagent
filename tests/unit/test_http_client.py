"""Unit tests for the shared HTTP client."""

from __future__ import annotations

import httpx

from hypeagent.config.schema import HttpConfig
from hypeagent.platforms.http_client import HttpClient


def _client(handler: httpx.MockTransport) -> HttpClient:
    return HttpClient(
        HttpConfig(timeout_seconds=5, retry_count=0),
        "hypeagent/1.0 test",
        client=httpx.Client(transport=handler),
    )


def test_request_sets_user_agent() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["user_agent"] = request.headers.get("User-Agent", "")
        return httpx.Response(200, json={"ok": True})

    with _client(httpx.MockTransport(handler)) as http:
        response = http.get("https://example.com/test")

    assert response.status_code == 200
    assert captured["user_agent"] == "hypeagent/1.0 test"


def test_request_retries_on_server_error() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    http = HttpClient(
        HttpConfig(timeout_seconds=5, retry_count=1),
        "hypeagent/1.0 test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with http:
        response = http.get("https://example.com/test")

    assert response.status_code == 200
    assert attempts["count"] == 2


def test_request_raises_after_exhausted_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with _client(httpx.MockTransport(handler)) as http:
        response = http.get("https://example.com/test")

    assert response.status_code == 500


def test_request_retries_on_transport_error() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json={"ok": True})

    http = HttpClient(
        HttpConfig(timeout_seconds=5, retry_count=1),
        "hypeagent/1.0 test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with http:
        response = http.get("https://example.com/test")

    assert response.status_code == 200
    assert attempts["count"] == 2
