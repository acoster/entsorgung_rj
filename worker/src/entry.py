"""Cloudflare Python Worker serving per-district waste collection calendars.

Routes:
    GET /<district-id>.ics   e.g. /2.ics for "Kreis 2"

All state lives in the `CACHE` KV namespace (see `entsorgung_rj.calendar_service`):
one long-lived upstream identity per district, the regions list, and the rendered
calendars (fresh for `CALENDAR_TTL_SECONDS`, default 4 hours).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from js import Object
from pyodide.ffi import to_js
from workers import Response, WorkerEntrypoint

from entsorgung_rj.calendar_service import (
    DEFAULT_CALENDAR_TTL,
    DistrictCalendarService,
    DistrictNotFoundError,
)
from entsorgung_rj.models import ApiError

_PATH_RE = re.compile(r"^/(\d{1,3})\.ics$")
_KV_MIN_TTL = 60  # Workers KV rejects expirationTtl < 60s


class WorkersKVStore:
    """Adapts a Workers KV binding to the `KeyValueStore` protocol."""

    def __init__(self, namespace) -> None:
        self._ns = namespace

    async def get(self, key: str) -> str | None:
        value = await self._ns.get(key)
        return value if isinstance(value, str) else None

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        if ttl is None:
            await self._ns.put(key, value)
            return
        options = to_js(
            {"expirationTtl": max(int(ttl), _KV_MIN_TTL)},
            dict_converter=Object.fromEntries,
        )
        await self._ns.put(key, value, options)


def _env_int(env, name: str, default: int) -> int:
    raw = getattr(env, name, None)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _text(body: str, status: int) -> Response:
    return Response(
        body,
        status=status,
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if request.method not in ("GET", "HEAD"):
            return _text("Method not allowed\n", 405)

        match = _PATH_RE.match(urlparse(request.url).path)
        if not match:
            return _text("Not found. Use /<district>.ics, e.g. /2.ics\n", 404)
        district_id = int(match.group(1))

        calendar_ttl = _env_int(self.env, "CALENDAR_TTL_SECONDS", DEFAULT_CALENDAR_TTL)
        service = DistrictCalendarService(
            WorkersKVStore(self.env.CACHE),
            calendar_ttl=calendar_ttl,
        )

        try:
            result = await service.get_calendar(district_id)
        except DistrictNotFoundError as exc:
            return _text(f"{exc}\n", 404)
        except ApiError as exc:
            print(f"upstream error for district {district_id}: {exc}")
            return _text("Upstream calendar service unavailable\n", 502)

        headers = {
            "Content-Type": "text/calendar; charset=utf-8",
            "Content-Disposition": f'inline; filename="kreis-{district_id}.ics"',
            "Cache-Control": f"public, max-age={min(calendar_ttl, 3600)}",
            "X-Calendar-Cache": "stale" if result.stale else "ok",
        }
        body = "" if request.method == "HEAD" else result.ics
        return Response(body, headers=headers)
