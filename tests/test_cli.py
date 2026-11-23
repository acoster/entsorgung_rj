"""Unit tests for `entsorgung_rj.cli` and package import isolation."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from entsorgung_rj.cli import build_parser, main
from entsorgung_rj.models import ApiError, ClientIdentity, DistrictSchedule


class TestPackageImportIsolation(unittest.TestCase):
    def test_top_level_import_does_not_load_cli_or_storage(self) -> None:
        code = (
            "import sys, entsorgung_rj; "
            "assert 'entsorgung_rj.cli' not in sys.modules; "
            "assert 'entsorgung_rj.storage' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class TestCliParser(unittest.TestCase):
    def test_json_and_ics_are_mutually_exclusive(self) -> None:
        parser = build_parser()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["Kreis 2", "--json", "--ics", "-"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_district_and_list_flag_errors(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_list_districts_with_ics_errors(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
            main(["--list-districts", "--ics", "-"])
        self.assertEqual(ctx.exception.code, 2)


class TestCliMain(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = ClientIdentity("uid-1", "tok-1", is_new=False)
        self.sample_schedule = DistrictSchedule(
            district={"id": 2, "name": "Kreis 2"},
            schedules=[
                {
                    "id": 10,
                    "scheduled_date_time": "2026-11-25T00:00:00Z",
                    "category_id": 1,
                    "category": {"name": "Papier"},
                },
            ],
            start_date="2026-11-22",
            end_date="2027-01-20",
        )

    def _run_main(
        self,
        argv: list[str],
        mock_client: mock.MagicMock,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch(
                "entsorgung_rj.cli.load_or_create_identity",
                return_value=self.identity,
            ),
            mock.patch("entsorgung_rj.cli.EntsorgungClient", return_value=mock_client),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_list_districts_text_and_json(self) -> None:
        mock_client = mock.MagicMock()
        mock_client.list_regions.return_value = [{"id": 1, "name": "Kreis 1"}]

        code, out, err = self._run_main(["--list-districts"], mock_client)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.strip(), "1  Kreis 1")

        code, out, err = self._run_main(["--list-districts", "--json"], mock_client)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), [{"id": 1, "name": "Kreis 1"}])

    def test_table_json_and_ics_outputs(self) -> None:
        mock_client = mock.MagicMock()
        mock_client.get_district_schedule.return_value = self.sample_schedule

        code, out, err = self._run_main(["Kreis 2", "--upcoming"], mock_client)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Kreis 2", out)
        self.assertIn("2026-11-25 (Wed)  Papier", out)
        mock_client.get_district_schedule.assert_called_with(
            "Kreis 2",
            upcoming=True,
            category=None,
        )

        code, out, err = self._run_main(["Kreis 2", "--json"], mock_client)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["district"]["id"], 2)

        code, out, err = self._run_main(["Kreis 2", "--ics", "-"], mock_client)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("BEGIN:VCALENDAR\r\n", out)
        self.assertIn("SUMMARY:Papier\r\n", out)

        with tempfile.TemporaryDirectory() as tmp:
            ics_path = Path(tmp) / "out.ics"
            code, out, err = self._run_main(
                ["Kreis 2", "--ics", str(ics_path)],
                mock_client,
            )
            self.assertEqual((code, err), (0, ""))
            self.assertIn("Wrote 1 events", out)
            self.assertIn(b"BEGIN:VCALENDAR\r\n", ics_path.read_bytes())

    def test_error_handling_returns_nonzero(self) -> None:
        mock_client = mock.MagicMock()

        mock_client.get_district_schedule.side_effect = ValueError("District not found")
        code, _, err = self._run_main(["Nope"], mock_client)
        self.assertEqual(code, 1)
        self.assertIn("District not found", err)

        mock_client.get_district_schedule.side_effect = ApiError(
            502,
            "Bad Gateway",
            "upstream down",
        )
        code, _, err = self._run_main(["Kreis 2"], mock_client)
        self.assertEqual(code, 1)
        self.assertIn("API error: HTTP 502: Bad Gateway", err)
        self.assertIn("Response body: upstream down", err)

        mock_client.get_district_schedule.side_effect = OSError("network unreachable")
        code, _, err = self._run_main(["Kreis 2"], mock_client)
        self.assertEqual(code, 1)
        self.assertIn("Network error: network unreachable", err)

        mock_client.get_district_schedule.side_effect = None
        mock_client.get_district_schedule.return_value = self.sample_schedule
        code, _, err = self._run_main(
            ["Kreis 2", "--ics", "/nonexistent_dir_xyz/out.ics"],
            mock_client,
        )
        self.assertEqual(code, 1)
        self.assertIn("Failed to write output:", err)


if __name__ == "__main__":
    unittest.main()
