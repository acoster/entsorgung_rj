"""Unit tests for `entsorgung_rj.ical`."""

from __future__ import annotations

import datetime as dt
import unittest

from entsorgung_rj.ical import (
    calendar_filename,
    escape_ics_text,
    format_ics,
    format_schedule_ics,
)
from entsorgung_rj.models import DistrictSchedule, WasteCategory


class TestIcal(unittest.TestCase):
    def test_calendar_filename(self) -> None:
        self.assertEqual(calendar_filename(2), "entsorgung-kreis-2.ics")
        self.assertEqual(calendar_filename(2, frozenset()), "entsorgung-kreis-2.ics")
        self.assertEqual(
            calendar_filename(2, [WasteCategory.PAPIER, WasteCategory.KEHRICHT]),
            "entsorgung-kreis-2-kehricht-papier.ics",
        )
        self.assertEqual(
            calendar_filename(2, set(WasteCategory)),
            "entsorgung-kreis-2.ics",
        )
        self.assertEqual(
            calendar_filename(7, {WasteCategory.GRUENGUT}),
            "entsorgung-kreis-7-gruengut.ics",
        )

    def test_escape_ics_text(self) -> None:
        raw = "A\\B;C,D\r\nE\nF"
        self.assertEqual(escape_ics_text(raw), r"A\\B\;C\,D\nE\nF")

    def test_format_ics_structure_crlf_and_escaping(self) -> None:
        schedules = [
            {
                "id": 42,
                "scheduled_date_time": "2026-11-30T00:00:00Z",
                "category_id": 3,
                "category": {"name": "Papier, Karton; Alt"},
            },
        ]
        now = dt.datetime(2026, 11, 22, 15, 30, 0, tzinfo=dt.timezone.utc)
        ics = format_ics("Kreis 2, Nord", schedules, now=now)

        self.assertTrue(ics.endswith("\r\n"))
        lines = ics.split("\r\n")
        self.assertEqual(lines[0], "BEGIN:VCALENDAR")
        self.assertIn("VERSION:2.0", lines)
        self.assertIn("X-WR-CALNAME:Entsorgung Kreis 2\\, Nord", lines)
        self.assertIn("UID:entsorgung-rj-42-3@adaptit.ch", lines)
        self.assertIn("DTSTAMP:20261122T153000Z", lines)
        # Month boundary rollover: Nov 30 -> Dec 1
        self.assertIn("DTSTART;VALUE=DATE:20261130", lines)
        self.assertIn("DTEND;VALUE=DATE:20261201", lines)
        self.assertIn("SUMMARY:Papier\\, Karton\\; Alt", lines)
        self.assertIn("LOCATION:Kreis 2\\, Nord", lines)
        self.assertEqual(lines[-2], "END:VCALENDAR")

    def test_format_ics_custom_cal_name_prodid_and_naive_now(self) -> None:
        now_naive = dt.datetime(2026, 1, 2, 3, 4, 5)
        ics = format_ics(
            "Kreis 1",
            [],
            cal_name="Custom; Cal",
            prodid="-//Custom//EN",
            now=now_naive,
        )
        self.assertIn("PRODID:-//Custom//EN\r\n", ics)
        self.assertIn("X-WR-CALNAME:Custom\\; Cal\r\n", ics)
        self.assertNotIn("BEGIN:VEVENT", ics)

    def test_format_schedule_ics_delegates_from_district_schedule(self) -> None:
        schedule = DistrictSchedule(
            district={"id": 2, "name": "Kreis 2"},
            schedules=[
                {
                    "id": 9,
                    "scheduled_date_time": "2026-12-01",
                    "category_id": 5,
                    "category": None,
                },
            ],
        )
        now = dt.datetime(2026, 11, 22, 10, 0, 0, tzinfo=dt.timezone.utc)
        ics = format_schedule_ics(schedule, now=now)
        self.assertIn("SUMMARY:Category 5\r\n", ics)
        self.assertIn("LOCATION:Kreis 2\r\n", ics)
        self.assertIn("DTSTART;VALUE=DATE:20261201\r\n", ics)
        self.assertIn("DTEND;VALUE=DATE:20261202\r\n", ics)


if __name__ == "__main__":
    unittest.main()
