"""Unit tests for `entsorgung_rj.formatters`."""

from __future__ import annotations

import json
import unittest

from entsorgung_rj.formatters import (
    format_districts,
    format_schedule_json,
    format_table,
)
from entsorgung_rj.models import DistrictSchedule


class TestFormatters(unittest.TestCase):
    def test_format_districts_plain_and_json(self) -> None:
        regions = [{"id": 1, "name": "Kreis 1"}, {"id": 10, "name": "Kreis 10"}]
        self.assertEqual(format_districts(regions), "  1  Kreis 1\n 10  Kreis 10")
        self.assertEqual(json.loads(format_districts(regions, as_json=True)), regions)

    def test_format_table_empty(self) -> None:
        self.assertEqual(
            format_table("Kreis 2", []),
            "No collection dates found for Kreis 2.",
        )

    def test_format_table_groups_same_day_and_includes_window(self) -> None:
        schedules = [
            {
                "scheduled_date_time": "2026-11-25T00:00:00Z",
                "category_id": 1,
                "category": {"name": "Papier"},
            },
            {
                "scheduled_date_time": "2026-11-23T00:00:00Z",
                "category_id": 2,
                "category": {"name": "Kehricht"},
            },
            {
                "scheduled_date_time": "2026-11-25T00:00:00Z",
                "category_id": 3,
                "category": {"name": "Karton"},
            },
        ]
        table = format_table(
            "Kreis 2",
            schedules,
            start_date="2026-11-22",
            end_date="2027-01-20",
        )
        lines = table.splitlines()
        self.assertEqual(
            lines[0],
            "Rubbish Collection Calendar — Kreis 2 (2026-11-22 to 2027-01-20)",
        )
        self.assertEqual(lines[1], "=" * len(lines[0]))
        self.assertEqual(lines[2], "2026-11-23 (Mon)  Kehricht")
        self.assertEqual(lines[3], "2026-11-25 (Wed)  Papier, Karton")

    def test_format_schedule_json(self) -> None:
        schedule = DistrictSchedule(
            district={"id": 2, "name": "Kreis 2"},
            schedules=[{"id": 1, "category": {"name": "Grüngut"}}],
            start_date="2026-11-22",
            end_date="2027-01-20",
        )
        raw = format_schedule_json(schedule)
        self.assertIn("Grüngut", raw)
        self.assertEqual(
            json.loads(raw),
            {
                "district": {"id": 2, "name": "Kreis 2"},
                "start_date": "2026-11-22",
                "end_date": "2027-01-20",
                "schedules": [{"id": 1, "category": {"name": "Grüngut"}}],
            },
        )


if __name__ == "__main__":
    unittest.main()
