"""Human-readable terminal and JSON formatters for districts and schedules."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from entsorgung_rj.models import get_category_name, parse_schedule_date

if TYPE_CHECKING:
    import datetime as dt

    from entsorgung_rj.models import DistrictSchedule


def format_districts(regions: list[dict[str, Any]], *, as_json: bool = False) -> str:
    """Format the list of available districts as JSON or plain text."""
    if as_json:
        return json.dumps(regions, indent=2, ensure_ascii=False)
    return "\n".join(f"{region['id']:>3}  {region['name']}" for region in regions)


def format_table(
    district_name: str,
    schedules: list[dict[str, Any]],
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Format collection schedules as a human-readable grouped table."""
    if not schedules:
        return f"No collection dates found for {district_name}."

    header = f"Rubbish Collection Calendar — {district_name}"
    if start_date and end_date:
        header += f" ({start_date} to {end_date})"
    lines = [header, "=" * len(header)]

    by_date: dict[dt.date, list[str]] = {}
    for item in schedules:
        date = parse_schedule_date(item)
        by_date.setdefault(date, []).append(get_category_name(item))

    for date in sorted(by_date):
        weekday = date.strftime("%a")
        cats = ", ".join(by_date[date])
        lines.append(f"{date.isoformat()} ({weekday})  {cats}")
    return "\n".join(lines)


def format_schedule_json(schedule: DistrictSchedule) -> str:
    """Format a `DistrictSchedule` as a pretty-printed JSON payload."""
    payload = {
        "district": schedule.district,
        "start_date": schedule.start_date,
        "end_date": schedule.end_date,
        "schedules": schedule.schedules,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
