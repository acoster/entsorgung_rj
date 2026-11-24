"""Cloudflare Python Worker serving per-district waste collection calendars.

Routes:
    GET /<district-id>.ics                    e.g. /2.ics for "Kreis 2"
    GET /<district-id>.ics?categories=1,5     only the given waste categories

Each GET of a feed is also counted in Workers Analytics Engine (`FEED_STATS`
binding, see `entsorgung_rj.feed_stats`), without IPs or full user agents; only
the client's ASN and country are taken from `request.cf`.

`categories` takes comma-separated IDs or names of `WasteCategory` (1=karton,
2=kehricht, 3=gruengut, 4=metall, 5=papier) and may be repeated. Omitted or
empty means all categories.

All state lives in the `CACHE` KV namespace (see `entsorgung_rj.calendar_service`):
one long-lived upstream identity per district, the regions list, and each district's
schedule (fresh for `CALENDAR_TTL_SECONDS`, default 4 hours), from which the `.ics`
is rendered per request.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from js import Object
from pyodide.ffi import to_js
from workers import Response, WorkerEntrypoint

from entsorgung_rj.calendar_service import (
    DEFAULT_CALENDAR_TTL,
    DistrictCalendarService,
    DistrictNotFoundError,
)
from entsorgung_rj.feed_stats import categories_label, feed_datapoint
from entsorgung_rj.ical import calendar_filename
from entsorgung_rj.models import ApiError, parse_categories

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


def _cf_property(request, name: str):
    """Read one `request.cf` property (ASN, country, ...), or None if unavailable.

    The Python SDK's `Request` wraps the JS request; depending on the SDK version
    `cf` sits on the wrapper or on the underlying `js_object`. Missing properties
    (e.g. under local dev) come back as None.
    """
    cf = getattr(request, "cf", None)
    if cf is None:
        cf = getattr(getattr(request, "js_object", None), "cf", None)
    if cf is None:
        return None
    value = getattr(cf, name, None)
    return value if isinstance(value, (int, float, str)) else None


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

        url = urlparse(request.url)
        match = _PATH_RE.match(url.path)
        if not match:
            return _text("Not found. Use /<district>.ics, e.g. /2.ics\n", 404)
        district_id = int(match.group(1))

        response, categories, cache = await self._calendar(request, url, district_id)
        if request.method == "GET":
            self._record(request, district_id, categories, cache, response.status)
        return response

    async def _calendar(self, request, url, district_id: int):
        """Return `(response, categories label, cache state)` for a feed request."""
        try:
            categories = parse_categories(parse_qs(url.query).get("categories"))
        except ValueError as exc:
            return _text(f"{exc}\n", 400), "invalid", "none"
        label = categories_label(categories)

        calendar_ttl = _env_int(self.env, "CALENDAR_TTL_SECONDS", DEFAULT_CALENDAR_TTL)
        service = DistrictCalendarService(
            WorkersKVStore(self.env.CACHE),
            calendar_ttl=calendar_ttl,
        )

        try:
            result = await service.get_calendar(district_id, categories)
        except DistrictNotFoundError as exc:
            return _text(f"{exc}\n", 404), label, "none"
        except ApiError as exc:
            print(f"upstream error for district {district_id}: {exc}")
            return _text("Upstream calendar service unavailable\n", 502), label, "none"

        headers = {
            "Content-Type": "text/calendar; charset=utf-8",
            "Content-Disposition": (
                f'inline; filename="{calendar_filename(district_id, categories)}"'
            ),
            "Cache-Control": f"public, max-age={min(calendar_ttl, 3600)}",
            "X-Calendar-Cache": "stale" if result.stale else "ok",
        }
        body = "" if request.method == "HEAD" else result.ics
        cache = "stale" if result.stale else "fresh"
        return Response(body, headers=headers), label, cache

    def _record(self, request, district_id, categories, cache, status) -> None:
        """Write a usage data point; never lets analytics break the feed."""
        dataset = getattr(self.env, "FEED_STATS", None)
        if dataset is None:
            return
        try:
            point = feed_datapoint(
                district_id=district_id,
                categories=categories,
                user_agent=request.headers.get("User-Agent"),
                cache=cache,
                status=int(status),
                asn=_cf_property(request, "asn"),
                as_organization=_cf_property(request, "asOrganization"),
                country=_cf_property(request, "country"),
            )
            dataset.writeDataPoint(to_js(point, dict_converter=Object.fromEntries))
        except Exception as exc:  # noqa: BLE001
            print(f"analytics write failed: {exc}")
