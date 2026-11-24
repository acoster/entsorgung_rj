"""Unit tests for `tools.check_instance` (no network)."""

from __future__ import annotations

import datetime as dt
import unittest

from entsorgung_rj.ical import format_ics
from tools.check_instance import Fetched, fetch_with_retries, parse_events, run

TODAY = dt.date(2026, 11, 24)
ITEMS = [
    {
        "id": 1,
        "scheduled_date_time": "2026-11-26T00:00:00Z",
        "category_id": 2,
        "category": {"name": "Kehricht"},
    },
    {
        "id": 2,
        "scheduled_date_time": "2026-12-03T00:00:00Z",
        "category_id": 5,
        "category": {"name": "Papier"},
    },
]


def calendar(items=ITEMS, *, cache="ok", filename="entsorgung-kreis-2.ics") -> Fetched:
    return Fetched(
        200,
        {
            "content-type": "text/calendar; charset=utf-8",
            "x-calendar-cache": cache,
            "content-disposition": f'inline; filename="{filename}"',
        },
        format_ics("Kreis 2", items),
    )


class FakeSite:
    """Healthy instance by default; override paths to inject failures."""

    def __init__(self, **overrides: Fetched) -> None:
        self.overrides = overrides
        self.requested: list[str] = []

    def __call__(self, url: str) -> Fetched:
        path = url.split("coster.li", 1)[1]
        self.requested.append(path)
        if path in self.overrides:
            return self.overrides[path]
        if path == "/":
            return Fetched(200, {}, "<title>Entsorgungskalender</title>")
        if path == "/2.ics?categories=papier":
            return calendar(
                [i for i in ITEMS if i["category_id"] == 5],
                filename="entsorgung-kreis-2-papier.ics",
            )
        if path == "/2.ics?categories=glas":
            return Fetched(400, {}, "Unknown waste category")
        if path == "/99.ics":
            return Fetched(404, {}, "District 99 not found")
        return calendar()


BASE = "https://entsorgung-rappi.coster.li"


class TestCheckInstance(unittest.TestCase):
    def test_parse_events(self) -> None:
        events = parse_events(calendar().body)
        self.assertEqual(
            [(e.date, e.summary) for e in events],
            [(dt.date(2026, 11, 26), "Kehricht"), (dt.date(2026, 12, 3), "Papier")],
        )

    def test_healthy_instance_passes(self) -> None:
        site = FakeSite()
        report = run(BASE, today=TODAY, get=site)
        self.assertEqual(report.failed, [])
        self.assertIn("/8.ics", site.requested)

    def test_reports_each_kind_of_problem(self) -> None:
        site = FakeSite(
            **{
                "/3.ics": Fetched(502, {}, "Upstream calendar service unavailable"),
                "/4.ics": calendar(cache="stale"),
                "/5.ics": calendar([]),
                "/6.ics": Fetched(200, {"content-type": "text/html"}, "<html>"),
                "/2.ics?categories=papier": calendar(filename="kreis-2.ics"),
                "/2.ics?categories=glas": Fetched(200, {}, ""),
            },
        )
        failed = "\n".join(run(BASE, today=TODAY, get=site).failed)
        self.assertIn("/3.ics status: HTTP 502", failed)
        self.assertIn("/4.ics fresh", failed)
        self.assertIn("/5.ics has upcoming collections", failed)
        self.assertIn("/6.ics is a calendar", failed)
        self.assertIn("category filter: unexpected events: ['Kehricht']", failed)
        self.assertIn("download filename", failed)
        self.assertIn("unknown category rejected", failed)

    def test_old_collections_only_is_a_failure(self) -> None:
        report = run(BASE, today=dt.date(2027, 3, 1), get=FakeSite())
        self.assertTrue(any("has upcoming collections" in f for f in report.failed))

    def test_retries_server_errors_then_succeeds(self) -> None:
        responses = [Fetched(502, {}, ""), Fetched(200, {}, "ok")]
        sleeps: list[float] = []
        resp = fetch_with_retries(
            "x",
            get=lambda _url: responses.pop(0),
            sleep=sleeps.append,
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(len(sleeps), 1)

    def test_gives_up_after_retries_and_skips_client_errors(self) -> None:
        calls: list[str] = []

        def always(status: int):
            def get(url: str) -> Fetched:
                calls.append(url)
                return Fetched(status, {}, "")

            return get

        resp = fetch_with_retries("a", get=always(503), retries=2, sleep=lambda _s: None)
        self.assertEqual((resp.status, len(calls)), (503, 3))
        calls.clear()
        resp = fetch_with_retries("b", get=always(404), retries=2, sleep=lambda _s: None)
        self.assertEqual((resp.status, len(calls)), (404, 1))

    def test_network_errors_are_retried_then_raised(self) -> None:
        attempts = []

        def broken(url: str) -> Fetched:
            attempts.append(url)
            raise OSError("connection reset")

        with self.assertRaises(OSError):
            fetch_with_retries("a", get=broken, retries=1, sleep=lambda _s: None)
        self.assertEqual(len(attempts), 2)


if __name__ == "__main__":
    unittest.main()
