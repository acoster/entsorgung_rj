"""Cached per-district iCalendar service for serverless runtimes (zero direct I/O).

Designed for the Cloudflare Worker in `worker/`, but runtime-agnostic: storage is
any async key-value store implementing `KeyValueStore` (e.g. a thin adapter over
Workers KV) and HTTP goes through any `AsyncTransport`.

Caching strategy (minimises upstream requests):

* **One identity per district** (`identity:<id>`): the backend stores the active
  district per `device-token`, so every district gets its own long-lived identity.
  Concurrent requests for different districts therefore never clash, and each
  identity is registered exactly once.
* **Regions list** (`regions`): cached for `regions_ttl` seconds and used to
  validate district IDs without touching the backend.
* **Rendered calendar** (`ics:<id>`): considered fresh for `calendar_ttl` seconds.
  Stale copies are kept for `stale_ttl` seconds and served if a refresh fails.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from entsorgung_rj.client import BASE_URL, AsyncEntsorgungClient
from entsorgung_rj.ical import format_ics
from entsorgung_rj.models import ApiError, ClientIdentity, generate_identity

if TYPE_CHECKING:
    from collections.abc import Callable

    from entsorgung_rj.transport import AsyncTransport

DEFAULT_CALENDAR_TTL = 4 * 60 * 60  # 4 hours
DEFAULT_REGIONS_TTL = 24 * 60 * 60  # 1 day
DEFAULT_STALE_TTL = 7 * 24 * 60 * 60  # 7 days

_IDENTITY_KEY = "identity:{}"
_CALENDAR_KEY = "ics:{}"
_REGIONS_KEY = "regions"


class KeyValueStore(Protocol):
    """Minimal async key-value store (e.g. Cloudflare Workers KV)."""

    async def get(self, key: str) -> str | None:
        """Return the stored value, or `None` if missing/expired."""
        ...

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        """Store `value`, optionally expiring after `ttl` seconds."""
        ...


class DistrictNotFoundError(LookupError):
    """Raised when the requested district ID does not exist upstream."""


@dataclass(frozen=True)
class CalendarResult:
    """Rendered calendar plus cache metadata."""

    ics: str
    fetched_at: float
    stale: bool = False


class DistrictCalendarService:
    """Serve per-district `.ics` calendars backed by a key-value cache."""

    def __init__(
        self,
        store: KeyValueStore,
        *,
        transport: AsyncTransport | None = None,
        base_url: str = BASE_URL,
        calendar_ttl: int = DEFAULT_CALENDAR_TTL,
        regions_ttl: int = DEFAULT_REGIONS_TTL,
        stale_ttl: int = DEFAULT_STALE_TTL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._transport = transport
        self._base_url = base_url
        self.calendar_ttl = calendar_ttl
        self.regions_ttl = regions_ttl
        self.stale_ttl = max(stale_ttl, calendar_ttl)
        self._clock = clock

    async def get_calendar(self, district_id: int) -> CalendarResult:
        """Return the district's calendar, refreshing it from upstream if stale.

        Raises `DistrictNotFoundError` for unknown districts and `ApiError`
        when upstream fails and no cached copy is available.
        """
        cached = await self._load_json(_CALENDAR_KEY.format(district_id))
        now = self._clock()
        if cached and now - float(cached["fetched_at"]) < self.calendar_ttl:
            return CalendarResult(ics=cached["ics"], fetched_at=cached["fetched_at"])

        try:
            return await self._refresh(district_id)
        except ApiError:
            if cached:
                return CalendarResult(
                    ics=cached["ics"],
                    fetched_at=cached["fetched_at"],
                    stale=True,
                )
            raise

    async def _refresh(self, district_id: int) -> CalendarResult:
        regions = await self._load_json(_REGIONS_KEY)
        if regions is not None and _find_region(regions, district_id) is None:
            msg = f"District {district_id} not found"
            raise DistrictNotFoundError(msg)

        identity = await self._load_identity(district_id)
        client = AsyncEntsorgungClient(
            identity,
            base_url=self._base_url,
            transport=self._transport,
        )

        if regions is None:
            regions = await client.list_regions()
            if regions:
                await self._put_json(_REGIONS_KEY, regions, ttl=self.regions_ttl)

        region = _find_region(regions, district_id)
        if region is None:
            msg = f"District {district_id} not found"
            raise DistrictNotFoundError(msg)

        # Re-asserting the district each refresh is one cheap request and makes
        # the identity self-healing if the backend ever forgets its preference.
        await client.select_region(district_id)
        if identity.is_new:
            await self._put_json(
                _IDENTITY_KEY.format(district_id),
                {
                    "anonymous_user_id": identity.anonymous_user_id,
                    "device_token": identity.device_token,
                },
            )

        schedule_resp = await client.get_schedules()
        items = schedule_resp.get("data", [])
        district_name = str(region.get("name") or f"Kreis {district_id}")
        fetched_at = self._clock()
        ics = format_ics(district_name, items if isinstance(items, list) else [])

        await self._put_json(
            _CALENDAR_KEY.format(district_id),
            {"fetched_at": fetched_at, "ics": ics},
            ttl=self.stale_ttl,
        )
        return CalendarResult(ics=ics, fetched_at=fetched_at)

    async def _load_identity(self, district_id: int) -> ClientIdentity:
        stored = await self._load_json(_IDENTITY_KEY.format(district_id))
        if (
            isinstance(stored, dict)
            and stored.get("anonymous_user_id")
            and stored.get("device_token")
        ):
            return generate_identity(
                stored["anonymous_user_id"],
                stored["device_token"],
                is_new=False,
            )
        return generate_identity()

    async def _load_json(self, key: str) -> Any:
        raw = await self._store.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def _put_json(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        await self._store.put(key, json.dumps(value), ttl=ttl)


def _find_region(regions: Any, district_id: int) -> dict[str, Any] | None:
    if not isinstance(regions, list):
        return None
    for region in regions:
        if isinstance(region, dict) and str(region.get("id")) == str(district_id):
            return region
    return None
