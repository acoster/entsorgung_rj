"""Command-line interface for retrieving Rapperswil-Jona waste collection calendars."""

from __future__ import annotations

import argparse
import http.client
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from entsorgung_rj.client import EntsorgungClient
from entsorgung_rj.formatters import (
    format_districts,
    format_schedule_json,
    format_table,
)
from entsorgung_rj.ical import format_schedule_ics
from entsorgung_rj.models import ApiError
from entsorgung_rj.storage import DEFAULT_STATE_PATH, load_or_create_identity

if TYPE_CHECKING:
    from entsorgung_rj.models import DistrictSchedule


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="entsorgung_rj",
        description=(
            "Retrieve rubbish collection calendars for Rapperswil-Jona districts."
        ),
    )
    parser.add_argument(
        "district",
        nargs="?",
        help='District name or numeric ID (e.g. "Kreis 2" or "2").',
    )
    parser.add_argument(
        "-l",
        "--list-districts",
        action="store_true",
        help="List all available Rapperswil-Jona districts and exit.",
    )
    parser.add_argument(
        "--upcoming",
        action="store_true",
        help="Only show collection dates from today onward.",
    )
    parser.add_argument(
        "--category",
        help=(
            "Filter by waste category name "
            "(case-insensitive substring, e.g. Kehricht, Papier)."
        ),
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output raw JSON instead of a formatted table.",
    )
    output_group.add_argument(
        "--ics",
        metavar="PATH",
        help="Export calendar in iCalendar (.ics) format (use '-' for stdout).",
    )
    parser.add_argument(
        "--user-id",
        default=os.environ.get("ENTSORGUNG_RJ_USER_ID"),
        help="Optional anonymous-user-id UUID (auto-generated and cached if omitted).",
    )
    parser.add_argument(
        "-t",
        "--token",
        default=os.environ.get("ENTSORGUNG_RJ_TOKEN"),
        help="Optional device-token string (auto-generated if omitted).",
    )
    return parser


def _write_schedule_output(
    args: argparse.Namespace,
    schedule: DistrictSchedule,
) -> None:
    if args.ics:
        ics_text = format_schedule_ics(schedule)
        if args.ics == "-":
            sys.stdout.write(ics_text)
        else:
            with Path(args.ics).open("w", encoding="utf-8", newline="") as fh:
                fh.write(ics_text)
            print(f"Wrote {len(schedule.schedules)} events to {args.ics}")
        return

    if args.as_json:
        print(format_schedule_json(schedule))
        return

    print(
        format_table(
            schedule.district_name,
            schedule.schedules,
            start_date=schedule.start_date,
            end_date=schedule.end_date,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.list_districts and not args.district:
        parser.error(
            "Provide a district name/ID (e.g. 'Kreis 2' or '2') "
            "or pass --list-districts.",
        )
    if args.list_districts and args.ics:
        parser.error("--ics cannot be used with --list-districts.")

    identity = load_or_create_identity(DEFAULT_STATE_PATH, args.user_id, args.token)
    client = EntsorgungClient(identity)

    try:
        if args.list_districts:
            regions = client.list_regions()
            print(format_districts(regions, as_json=args.as_json))
            return 0

        schedule = client.get_district_schedule(
            args.district,
            upcoming=args.upcoming,
            category=args.category,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        if exc.body:
            print(f"Response body: {exc.body}", file=sys.stderr)
        return 1
    except (OSError, http.client.HTTPException) as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 1

    try:
        _write_schedule_output(args, schedule)
    except OSError as exc:
        print(f"Failed to write output: {exc}", file=sys.stderr)
        return 1

    return 0
