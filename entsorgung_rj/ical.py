"""Pure RFC 5545 iCalendar (.ics) serialization (zero I/O, Worker-safe)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from entsorgung_rj.models import WasteCategory, get_category_name, parse_schedule_date

if TYPE_CHECKING:
    from collections.abc import Iterable

    from entsorgung_rj.models import DistrictSchedule

ICS_PRODID = "-//Entsorgung RJ//Rapperswil-Jona//EN"


def escape_ics_text(value: str) -> str:
    """Escape special characters in an RFC 5545 TEXT property value."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\r\n", r"\n")
        .replace("\n", r"\n")
    )


def calendar_filename(
    district_id: int,
    categories: Iterable[WasteCategory] | None = None,
) -> str:
    """Suggested download name, e.g. `entsorgung-kreis-2-kehricht-papier.ics`.

    Categories are listed in ID order; none or all of them add no suffix.
    """
    selected = set(categories or ())
    parts = [f"entsorgung-kreis-{district_id}"]
    if selected != set(WasteCategory):
        parts.extend(c.name.lower() for c in sorted(selected))
    return "-".join(parts) + ".ics"


def format_ics(
    district_name: str,
    schedules: list[dict[str, Any]],
    *,
    cal_name: str | None = None,
    prodid: str = ICS_PRODID,
    now: dt.datetime | None = None,
) -> str:
    """Format collection schedules as an RFC 5545 iCalendar (.ics) document."""
    timestamp = now or dt.datetime.now(dt.timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    now_stamp = timestamp.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    escaped_district = escape_ics_text(district_name)
    calendar_name = escape_ics_text(cal_name or f"Entsorgung {district_name}")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{prodid}",
        f"X-WR-CALNAME:{calendar_name}",
    ]
    for item in schedules:
        date = parse_schedule_date(item)
        next_day = date + dt.timedelta(days=1)
        cat_name = escape_ics_text(get_category_name(item))
        item_id = item.get("id", date.isoformat())
        cat_id = item.get("category_id", 0)
        uid = f"entsorgung-rj-{item_id}-{cat_id}@adaptit.ch"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_stamp}",
                f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{next_day.strftime('%Y%m%d')}",
                f"SUMMARY:{cat_name}",
                f"LOCATION:{escaped_district}",
                "END:VEVENT",
            ],
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def format_schedule_ics(
    schedule: DistrictSchedule,
    *,
    cal_name: str | None = None,
    prodid: str = ICS_PRODID,
    now: dt.datetime | None = None,
) -> str:
    """Format a `DistrictSchedule` as an RFC 5545 iCalendar (.ics) document."""
    return format_ics(
        schedule.district_name,
        schedule.schedules,
        cal_name=cal_name,
        prodid=prodid,
        now=now,
    )
