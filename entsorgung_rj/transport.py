"""Pluggable sync and async HTTP transports (stdlib and Cloudflare fetch)."""

from __future__ import annotations

import http
import http.client
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

DEFAULT_TIMEOUT = 15.0


@dataclass(frozen=True)
class HttpRequest:
    """Transport-agnostic HTTP request."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None = None
    timeout: float = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class HttpResponse:
    """Transport-agnostic HTTP response."""

    status: int
    reason: str
    body: str


class SyncTransport(Protocol):
    """Synchronous HTTP transport protocol."""

    def send(self, request: HttpRequest) -> HttpResponse:
        """Send an HTTP request and return the decoded response."""
        ...


class AsyncTransport(Protocol):
    """Asynchronous HTTP transport protocol."""

    async def send(self, request: HttpRequest) -> HttpResponse:
        """Send an HTTP request asynchronously and return the decoded response."""
        ...


class HttpClientTransport:
    """Synchronous stdlib transport backed by `http.client`."""

    def send(self, request: HttpRequest) -> HttpResponse:
        """Execute `request` using `http.client.HTTPConnection` / `HTTPSConnection`."""
        parsed_url = urllib.parse.urlparse(request.url)
        conn_cls = (
            http.client.HTTPSConnection
            if parsed_url.scheme == "https"
            else http.client.HTTPConnection
        )
        conn = conn_cls(parsed_url.netloc, timeout=request.timeout)
        path = parsed_url.path + (f"?{parsed_url.query}" if parsed_url.query else "")
        try:
            conn.request(
                request.method,
                path,
                body=request.body,
                headers=request.headers,
            )
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            return HttpResponse(status=resp.status, reason=resp.reason, body=body)
        finally:
            conn.close()


def _resolve_default_fetch() -> Callable[..., Awaitable[Any]]:
    """Locate an async `fetch` function in Cloudflare Workers or Pyodide runtimes."""
    try:
        from workers import fetch  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        return fetch

    try:
        from pyodide.http import pyfetch  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        return pyfetch

    msg = (
        "No async fetch implementation found. Run inside Cloudflare Python Workers "
        "(workers.fetch) / Pyodide (pyodide.http.pyfetch), or pass a custom "
        "fetch_fn to FetchTransport(fetch_fn=...)."
    )
    raise RuntimeError(msg)


def _status_reason(status: int, response: object) -> str:
    reason = getattr(response, "statusText", None) or getattr(
        response,
        "status_text",
        None,
    )
    if reason:
        return str(reason)
    try:
        return http.HTTPStatus(status).phrase
    except ValueError:
        return ""


class FetchTransport:
    """Asynchronous transport for Cloudflare Python Workers and Pyodide `fetch`."""

    def __init__(
        self,
        fetch_fn: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._fetch_fn = fetch_fn

    async def send(self, request: HttpRequest) -> HttpResponse:
        """Execute `request` via `workers.fetch`, `pyodide.http.pyfetch`, or custom."""
        fetch_fn = self._fetch_fn or _resolve_default_fetch()
        kwargs: dict[str, Any] = {
            "method": request.method,
            "headers": dict(request.headers),
        }
        if request.body is not None:
            kwargs["body"] = request.body.decode("utf-8")

        response = await fetch_fn(request.url, **kwargs)
        status = int(response.status)

        if hasattr(response, "text"):
            body = str(await response.text())
        elif hasattr(response, "string"):
            body = str(await response.string())
        else:
            msg = "Fetch response object does not expose .text() or .string()."
            raise TypeError(msg)

        return HttpResponse(
            status=status,
            reason=_status_reason(status, response),
            body=body,
        )
