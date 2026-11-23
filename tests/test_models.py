"""Unit tests for `entsorgung_rj.models`."""

from __future__ import annotations

import datetime as dt
import unittest
import uuid

from entsorgung_rj.models import (
    ApiError,
    ClientIdentity,
    DistrictSchedule,
    filter_schedules,
    generate_identity,
    get_category_name,
    parse_schedule_date,
    resolve_district,
)


class TestModels(unittest.TestCase):
    def test_api_error_attributes_and_message(self) -> None:
        err = ApiError(401, "GET regions -> Unauthenticated", '{"message":"nope"}')
        self.assertEqual(err.status, 401)
        self.assertEqual(err.body, '{"message":"nope"}')
        self.assertEqual(str(err), "HTTP 401: GET regions -> Unauthenticated")

    def test_client_identity_tuple_and_attributes(self) -> None:
        ident = ClientIdentity("uid-1", "tok-1", is_new=False)
        uid, tok, is_new = ident
        self.assertEqual((uid, tok, is_new), ("uid-1", "tok-1", False))
        self.assertEqual(ident.anonymous_user_id, "uid-1")
        self.assertEqual(ident.device_token, "tok-1")
        self.assertFalse(ident.is_new)

    def test_district_schedule_properties(self) -> None:
        schedule = DistrictSchedule(
            district={"id": "2", "name": "Kreis 2"},
            schedules=[],
            start_date="2026-11-22",
            end_date="2027-01-20",
        )
        self.assertEqual(schedule.district_id, 2)
        self.assertEqual(schedule.district_name, "Kreis 2")

    def test_generate_identity_defaults_to_uuid4(self) -> None:
        ident = generate_identity()
        parsed = uuid.UUID(ident.anonymous_user_id)
        self.assertEqual(parsed.version, 4)
        self.assertEqual(ident.device_token, f"cli-{ident.anonymous_user_id}")
        self.assertTrue(ident.is_new)

    def test_generate_identity_overrides_and_stripping(self) -> None:
        ident = generate_identity("  custom-uid  ", "  custom-tok ", is_new=False)
        self.assertEqual(ident.anonymous_user_id, "custom-uid")
        self.assertEqual(ident.device_token, "custom-tok")
        self.assertFalse(ident.is_new)


class TestResolveDistrict(unittest.TestCase):
    def setUp(self) -> None:
        self.regions = [
            {"id": 1, "name": "Kreis 1"},
            {"id": 2, "name": "Kreis 2"},
            {"id": 3, "name": "Kempraten"},
        ]

    def test_match_by_numeric_id_int_or_str(self) -> None:
        self.assertEqual(resolve_district(2, self.regions)["name"], "Kreis 2")
        self.assertEqual(resolve_district(" 1 ", self.regions)["name"], "Kreis 1")

    def test_match_by_exact_name_case_insensitive(self) -> None:
        self.assertEqual(resolve_district("  kreis 2 ", self.regions)["id"], 2)

    def test_match_by_unique_substring(self) -> None:
        self.assertEqual(resolve_district("kemp", self.regions)["id"], 3)

    def test_ambiguous_substring_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_district("kreis", self.regions)
        self.assertIn("Ambiguous district", str(ctx.exception))
        self.assertIn("Kreis 1 (id=1)", str(ctx.exception))
        self.assertIn("Kreis 2 (id=2)", str(ctx.exception))

    def test_unknown_district_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_district("Nowhere", self.regions)
        self.assertIn("not found", str(ctx.exception))
        self.assertIn("Kempraten (id=3)", str(ctx.exception))

    def test_unknown_numeric_id_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_district(99, self.regions)


class TestScheduleHelpers(unittest.TestCase):
    def test_parse_schedule_date_variants(self) -> None:
        self.assertEqual(
            parse_schedule_date({"scheduled_date_time": "2026-11-25T00:00:00Z"}),
            dt.date(2026, 11, 25),
        )
        self.assertEqual(
            parse_schedule_date({"scheduled_date_time": "2026-11-25T07:30:00+01:00"}),
            dt.date(2026, 11, 25),
        )
        self.assertEqual(
            parse_schedule_date({"scheduled_date_time": "2026-11-25 00:00:00 invalid"}),
            dt.date(2026, 11, 25),
        )

    def test_get_category_name_present_and_fallbacks(self) -> None:
        self.assertEqual(
            get_category_name({"category_id": 1, "category": {"name": "Papier"}}),
            "Papier",
        )
        self.assertEqual(
            get_category_name({"category_id": 4, "category": None}),
            "Category 4",
        )
        self.assertEqual(
            get_category_name({"category_id": 5, "category": {}}),
            "Category 5",
        )

    def test_filter_schedules_sorts_and_filters(self) -> None:
        items = [
            {
                "id": 2,
                "scheduled_date_time": "2026-11-28T00:00:00Z",
                "category_id": 1,
                "category": {"name": "Papier"},
            },
            {
                "id": 1,
                "scheduled_date_time": "2026-11-20T00:00:00Z",
                "category_id": 2,
                "category": {"name": "Kehricht"},
            },
            {
                "id": 3,
                "scheduled_date_time": "2026-11-22T00:00:00Z",
                "category_id": 3,
                "category": {"name": "Grüngut"},
            },
            {
                "id": 4,
                "scheduled_date_time": "2026-11-24T00:00:00Z",
                "category_id": 4,
                "category": None,
            },
        ]

        sorted_all = filter_schedules(items)
        self.assertEqual([i["id"] for i in sorted_all], [1, 3, 4, 2])
        # Original list must not be mutated
        self.assertEqual([i["id"] for i in items], [2, 1, 3, 4])

        upcoming = filter_schedules(
            items,
            upcoming=True,
            today=dt.date(2026, 11, 22),
        )
        self.assertEqual([i["id"] for i in upcoming], [3, 4, 2])

        by_cat = filter_schedules(items, category="  PAP ")
        self.assertEqual([i["id"] for i in by_cat], [2])

        combined = filter_schedules(
            items,
            upcoming=True,
            category="kehricht",
            today=dt.date(2026, 11, 22),
        )
        self.assertEqual(combined, [])


if __name__ == "__main__":
    unittest.main()
