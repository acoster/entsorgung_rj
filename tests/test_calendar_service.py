"""Unit tests for `entsorgung_rj.calendar_service`."""

from __future__ import annotations

import json
import unittest
from typing import Any

from entsorgung_rj.calendar_service import (
    DEFAULT_CALENDAR_TTL,
    DistrictCalendarService,
    DistrictNotFoundError,
)
from entsorgung_rj.models import ApiError
from entsorgung_rj.transport import HttpRequest, HttpResponse

REGIONS = [{"id": i, "name": f"Kreis {i}"} for i in range(1, 9)]


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        self.data[key] = value
        self.ttls[key] = ttl


class FakeBackend:
    """Simulates the upstream API, tracking each token's selected region."""

    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self.registered: set[str] = set()
        self.region_by_token: dict[str, int] = {}
        self.fail = False

    def endpoints(self) -> list[str]:
        return [r.url.rsplit("/", 1)[-1] for r in self.requests]

    async def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if self.fail:
            return HttpResponse(503, "Service Unavailable", "")
        endpoint = request.url.rsplit("/", 1)[-1]
        body = json.loads(request.body) if request.body else {}
        token = request.headers.get("device-token") or body.get("device-token")

        if endpoint == "register-device":
            self.registered.add(token)
            return _ok({"success": True})
        if token not in self.registered:
            return HttpResponse(401, "Unauthorized", '{"message": "unknown"}')
        if endpoint == "regions":
            return _ok({"data": REGIONS})
        if endpoint == "set-region-preference":
            self.region_by_token[token] = body["region-id"]
            return _ok({"success": True})
        if endpoint == "collection-schedule":
            region = self.region_by_token.get(token, 1)
            return _ok(
                {
                    "data": {
                        "start_date": "2026-11-23",
                        "end_date": "2027-01-22",
                        "data": [
                            {
                                "id": region * 100,
                                "scheduled_date_time": "2026-11-30T00:00:00Z",
                                "category_id": 1,
                                "category": {"name": f"Papier R{region}"},
                            },
                        ],
                    },
                },
            )
        return HttpResponse(404, "Not Found", "")


def _ok(payload: Any) -> HttpResponse:
    return HttpResponse(200, "OK", json.dumps(payload))


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class TestDistrictCalendarService(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.backend = FakeBackend()
        self.clock = Clock()
        self.service = DistrictCalendarService(
            self.store,
            transport=self.backend,
            clock=self.clock,
        )

    async def test_first_request_registers_selects_and_caches(self) -> None:
        result = await self.service.get_calendar(2)

        self.assertIn("SUMMARY:Papier R2", result.ics)
        self.assertIn("X-WR-CALNAME:Entsorgung Kreis 2", result.ics)
        self.assertFalse(result.stale)
        self.assertEqual(
            self.backend.endpoints(),
            [
                "register-device",
                "regions",
                "set-region-preference",
                "collection-schedule",
            ],
        )
        self.assertIn("identity:2", self.store.data)
        self.assertIn("regions", self.store.data)
        self.assertIn("ics:2", self.store.data)
        self.assertIsNone(self.store.ttls["identity:2"])

    async def test_fresh_cache_hit_makes_no_requests(self) -> None:
        first = await self.service.get_calendar(2)
        self.backend.requests.clear()
        self.clock.now += DEFAULT_CALENDAR_TTL - 1

        second = await self.service.get_calendar(2)

        self.assertEqual(self.backend.requests, [])
        self.assertEqual(first.ics, second.ics)

    async def test_expired_cache_reuses_identity_and_regions(self) -> None:
        await self.service.get_calendar(2)
        identity = json.loads(self.store.data["identity:2"])
        self.backend.requests.clear()
        self.clock.now += DEFAULT_CALENDAR_TTL + 1

        await self.service.get_calendar(2)

        self.assertEqual(
            self.backend.endpoints(),
            ["set-region-preference", "collection-schedule"],
        )
        self.assertTrue(
            all(
                r.headers.get("device-token") == identity["device_token"]
                for r in self.backend.requests
            ),
        )
        self.assertEqual(json.loads(self.store.data["identity:2"]), identity)

    async def test_each_district_gets_its_own_identity(self) -> None:
        r2 = await self.service.get_calendar(2)
        r5 = await self.service.get_calendar(5)

        id2 = json.loads(self.store.data["identity:2"])
        id5 = json.loads(self.store.data["identity:5"])
        self.assertNotEqual(id2["device_token"], id5["device_token"])
        self.assertIn("Papier R2", r2.ics)
        self.assertIn("Papier R5", r5.ics)
        # Second district: regions come from cache, only its own identity registers.
        self.assertEqual(self.backend.endpoints().count("regions"), 1)
        self.assertEqual(self.backend.endpoints().count("register-device"), 2)

    async def test_unknown_district_with_cached_regions_skips_backend(self) -> None:
        await self.service.get_calendar(1)
        self.backend.requests.clear()

        with self.assertRaises(DistrictNotFoundError):
            await self.service.get_calendar(99)

        self.assertEqual(self.backend.requests, [])
        self.assertNotIn("identity:99", self.store.data)

    async def test_unknown_district_cold_does_not_persist_identity(self) -> None:
        with self.assertRaises(DistrictNotFoundError):
            await self.service.get_calendar(99)
        self.assertNotIn("identity:99", self.store.data)
        self.assertIn("regions", self.store.data)

    async def test_backend_forgot_identity_reregisters(self) -> None:
        await self.service.get_calendar(3)
        self.backend.registered.clear()
        self.backend.requests.clear()
        self.clock.now += DEFAULT_CALENDAR_TTL + 1

        result = await self.service.get_calendar(3)

        self.assertIn("Papier R3", result.ics)
        self.assertEqual(
            self.backend.endpoints(),
            [
                "set-region-preference",
                "register-device",
                "set-region-preference",
                "collection-schedule",
            ],
        )

    async def test_serves_stale_calendar_when_backend_fails(self) -> None:
        fresh = await self.service.get_calendar(4)
        self.backend.fail = True
        self.clock.now += DEFAULT_CALENDAR_TTL + 1

        result = await self.service.get_calendar(4)

        self.assertTrue(result.stale)
        self.assertEqual(result.ics, fresh.ics)

    async def test_backend_failure_without_cache_raises(self) -> None:
        self.backend.fail = True
        with self.assertRaises(ApiError):
            await self.service.get_calendar(4)


if __name__ == "__main__":
    unittest.main()
