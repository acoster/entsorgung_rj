"""Unit tests for `entsorgung_rj.client` (sync and async)."""

from __future__ import annotations

import datetime as dt
import json
import unittest
from typing import Any

from entsorgung_rj.client import AsyncEntsorgungClient, EntsorgungClient
from entsorgung_rj.models import ApiError, ClientIdentity
from entsorgung_rj.transport import HttpRequest, HttpResponse


class RecordingSyncTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self._responses.pop(0)


class RecordingAsyncTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[HttpRequest] = []

    async def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def _json_response(payload: Any, status: int = 200, reason: str = "OK") -> HttpResponse:
    return HttpResponse(status=status, reason=reason, body=json.dumps(payload))


class TestSyncEntsorgungClient(unittest.TestCase):
    def setUp(self) -> None:
        self.new_identity = ClientIdentity("uid-1", "tok-1", is_new=True)
        self.cached_identity = ClientIdentity("uid-1", "tok-1", is_new=False)

    def test_register_device_omits_auth_headers_and_sends_body(self) -> None:
        transport = RecordingSyncTransport([_json_response({"success": True})])
        client = EntsorgungClient(self.new_identity, transport=transport)

        resp = client.register_device()
        self.assertEqual(resp, {"success": True})
        req = transport.requests[0]
        self.assertEqual(req.method, "POST")
        self.assertTrue(req.url.endswith("/register-device"))
        self.assertNotIn("anonymous-user-id", req.headers)
        self.assertNotIn("device-token", req.headers)
        self.assertEqual(
            req.headers["User-Agent"],
            "entsorgung-rj/0.1 (+https://github.com/acoster/entsorgung_rj)",
        )
        assert req.body is not None
        self.assertEqual(
            json.loads(req.body.decode("utf-8")),
            {"device-token": "tok-1", "anonymous-user-id": "uid-1"},
        )

    def test_get_district_schedule_new_identity_registers_first(self) -> None:
        transport = RecordingSyncTransport(
            [
                _json_response({"success": True}),
                _json_response(
                    {
                        "data": [
                            {"id": 1, "name": "Kreis 1"},
                            {"id": 2, "name": "Kreis 2"},
                        ]
                    }
                ),
                _json_response({"success": True}),
                _json_response(
                    {
                        "data": {
                            "start_date": "2026-11-22",
                            "end_date": "2027-01-20",
                            "data": [
                                {
                                    "id": 10,
                                    "scheduled_date_time": "2026-11-25T00:00:00Z",
                                    "category_id": 1,
                                    "category": {"name": "Papier"},
                                },
                                {
                                    "id": 11,
                                    "scheduled_date_time": "2026-11-20T00:00:00Z",
                                    "category_id": 2,
                                    "category": {"name": "Kehricht"},
                                },
                            ],
                        },
                    },
                ),
            ],
        )
        client = EntsorgungClient(self.new_identity, transport=transport)
        schedule = client.get_district_schedule(
            "Kreis 2",
            upcoming=True,
            today=dt.date(2026, 11, 22),
        )

        endpoints = [r.url.rsplit("/", 1)[-1] for r in transport.requests]
        self.assertEqual(
            endpoints,
            [
                "register-device",
                "regions",
                "set-region-preference",
                "collection-schedule",
            ],
        )
        self.assertEqual(schedule.district_id, 2)
        self.assertEqual(schedule.district_name, "Kreis 2")
        self.assertEqual(schedule.start_date, "2026-11-22")
        self.assertEqual(schedule.end_date, "2027-01-20")
        self.assertEqual([s["id"] for s in schedule.schedules], [10])

    def test_cached_identity_reregisters_once_on_401(self) -> None:
        transport = RecordingSyncTransport(
            [
                _json_response(
                    {"message": "Unauthenticated"}, status=401, reason="Unauthorized"
                ),
                _json_response({"success": True}),
                _json_response({"data": [{"id": 2, "name": "Kreis 2"}]}),
            ],
        )
        client = EntsorgungClient(self.cached_identity, transport=transport)
        regions = client.list_regions()

        self.assertEqual(regions, [{"id": 2, "name": "Kreis 2"}])
        endpoints = [r.url.rsplit("/", 1)[-1] for r in transport.requests]
        self.assertEqual(endpoints, ["regions", "register-device", "regions"])

    def test_cached_identity_does_not_retry_twice(self) -> None:
        transport = RecordingSyncTransport(
            [
                _json_response(
                    {"message": "Unauthorized"}, status=401, reason="Unauthorized"
                ),
                _json_response({"success": True}),
                _json_response(
                    {"message": "Still denied"}, status=401, reason="Unauthorized"
                ),
            ],
        )
        client = EntsorgungClient(self.cached_identity, transport=transport)
        with self.assertRaises(ApiError) as ctx:
            client.list_regions()
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("Still denied", str(ctx.exception))
        self.assertEqual(len(transport.requests), 3)

    def test_500_error_does_not_trigger_reregistration(self) -> None:
        transport = RecordingSyncTransport(
            [HttpResponse(status=500, reason="Internal Server Error", body="boom")],
        )
        client = EntsorgungClient(self.cached_identity, transport=transport)
        with self.assertRaises(ApiError) as ctx:
            client.list_regions()
        self.assertEqual(ctx.exception.status, 500)
        self.assertIn("Internal Server Error", str(ctx.exception))
        self.assertEqual(len(transport.requests), 1)

    def test_invalid_json_body_raises_api_error(self) -> None:
        transport = RecordingSyncTransport(
            [HttpResponse(status=200, reason="OK", body="<html>not json</html>")],
        )
        client = EntsorgungClient(self.cached_identity, transport=transport)
        with self.assertRaises(ApiError) as ctx:
            client.get_regions()
        self.assertIn("invalid JSON response", str(ctx.exception))

    def test_list_shaped_schedules_response_is_normalized(self) -> None:
        transport = RecordingSyncTransport(
            [
                _json_response(
                    {"data": [{"id": 1, "scheduled_date_time": "2026-11-25"}]}
                )
            ],
        )
        client = EntsorgungClient(self.cached_identity, transport=transport)
        self.assertEqual(
            client.get_schedules(),
            {"data": [{"id": 1, "scheduled_date_time": "2026-11-25"}]},
        )


class TestAsyncEntsorgungClient(unittest.IsolatedAsyncioTestCase):
    async def test_async_get_district_schedule_and_reregister_on_set_region_400(
        self,
    ) -> None:
        transport = RecordingAsyncTransport(
            [
                _json_response({"data": [{"id": 2, "name": "Kreis 2"}]}),
                _json_response(
                    {"message": "Device not found"}, status=400, reason="Bad Request"
                ),
                _json_response({"success": True}),
                _json_response({"success": True}),
                _json_response(
                    {
                        "data": {
                            "start_date": "2026-11-22",
                            "end_date": "2027-01-20",
                            "data": [
                                {
                                    "id": 7,
                                    "scheduled_date_time": "2026-12-01T00:00:00Z",
                                    "category_id": 1,
                                    "category": {"name": "Papier"},
                                },
                            ],
                        },
                    },
                ),
            ],
        )
        identity = ClientIdentity("uid-async", "tok-async", is_new=False)
        client = AsyncEntsorgungClient(identity, transport=transport)

        schedule = await client.get_district_schedule("2", category="papier")
        endpoints = [r.url.rsplit("/", 1)[-1] for r in transport.requests]
        self.assertEqual(
            endpoints,
            [
                "regions",
                "set-region-preference",
                "register-device",
                "set-region-preference",
                "collection-schedule",
            ],
        )
        self.assertEqual(schedule.district_name, "Kreis 2")
        self.assertEqual([s["id"] for s in schedule.schedules], [7])

    async def test_async_new_identity_registers_before_list_regions(self) -> None:
        transport = RecordingAsyncTransport(
            [
                _json_response({"success": True}),
                _json_response({"data": [{"id": 1, "name": "Kreis 1"}]}),
            ],
        )
        identity = ClientIdentity("uid-new", "tok-new", is_new=True)
        client = AsyncEntsorgungClient(identity, transport=transport)

        regions = await client.list_regions()
        self.assertEqual(regions, [{"id": 1, "name": "Kreis 1"}])
        endpoints = [r.url.rsplit("/", 1)[-1] for r in transport.requests]
        self.assertEqual(endpoints, ["register-device", "regions"])


if __name__ == "__main__":
    unittest.main()
