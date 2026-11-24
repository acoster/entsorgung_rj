"""Unit tests for `entsorgung_rj.feed_stats`."""

from __future__ import annotations

import unittest

from entsorgung_rj.feed_stats import categories_label, classify_client, feed_datapoint
from entsorgung_rj.models import WasteCategory


class TestFeedStats(unittest.TestCase):
    def test_classify_client(self) -> None:
        cases = {
            None: "unknown",
            "": "unknown",
            "Google-Calendar-Importer": "google",
            "iOS/18.1 (22B83) dataaccessd/1.0": "apple",
            "macOS/15.1 (24B83) CalendarAgent/1000": "apple",
            "Microsoft Office/16.0 (Windows NT 10.0; Microsoft Outlook 16.0)": "outlook",
            "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Thunderbird/128.0": "thunderbird",
            "ICSx5/2.2 (ical4j/3.2; okhttp/4.12; Android 14)": "davx5",
            "Mozilla/5.0 (Windows NT 10.0) Chrome/131.0 Safari/537.36": "browser",
            "iOS/18.1 (22B83) remindd/1.0": "apple",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) "
            "AppleWebKit/605.1.15 CriOS/131.0 Mobile/15E148 Safari/604.1": "browser",
            "curl/8.5.0": "other",
            "entsorgung-rj-monitor/1.0 (+https://github.com/acoster/entsorgung_rj)": (
                "monitor"
            ),
        }
        for ua, expected in cases.items():
            with self.subTest(ua=ua):
                self.assertEqual(classify_client(ua), expected)

    def test_categories_label(self) -> None:
        self.assertEqual(categories_label(None), "all")
        self.assertEqual(categories_label(frozenset()), "all")
        self.assertEqual(
            categories_label({WasteCategory.PAPIER, WasteCategory.KEHRICHT}),
            "2,5",
        )

    def test_feed_datapoint_has_no_identifying_data(self) -> None:
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) Safari/604.1"
        point = feed_datapoint(
            district_id=3,
            categories="2,5",
            user_agent=ua,
            cache="fresh",
            status=200,
        )
        self.assertEqual(
            point,
            {
                "indexes": ["3"],
                "blobs": [
                    "3",
                    "2,5",
                    "browser",
                    "fresh",
                    "200",
                    "unknown",
                    "unknown",
                    "unknown",
                ],
                "doubles": [1],
            },
        )
        self.assertNotIn(ua, str(point))

    def test_feed_datapoint_network_fields(self) -> None:
        point = feed_datapoint(
            district_id=2,
            categories="all",
            user_agent="Google-Calendar-Importer",
            cache="fresh",
            status=200,
            asn=15169,
            as_organization="  Google   LLC ",
            country="us",
        )
        self.assertEqual(point["blobs"][5:], ["15169", "Google LLC", "US"])

    def test_feed_datapoint_network_fields_fallbacks(self) -> None:
        cases = [
            ({"asn": 0, "as_organization": "", "country": "XX"}, ["unknown"] * 3),
            ({"asn": "abc", "as_organization": None, "country": None}, ["unknown"] * 3),
            (
                {"asn": 3303.0, "as_organization": "Swisscom", "country": "T1"},
                ["3303", "Swisscom", "T1"],
            ),
            (
                {"asn": 1, "as_organization": "x" * 500, "country": "CH"},
                ["1", "x" * 96, "CH"],
            ),
        ]
        for kwargs, expected in cases:
            with self.subTest(**kwargs):
                point = feed_datapoint(
                    district_id=1,
                    categories="all",
                    user_agent=None,
                    cache="none",
                    status=404,
                    **kwargs,
                )
                self.assertEqual(point["blobs"][5:], expected)


if __name__ == "__main__":
    unittest.main()
