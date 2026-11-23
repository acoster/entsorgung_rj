"""Pure domain models, exceptions, and schedule helpers (zero I/O)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, NamedTuple


class ApiError(RuntimeError):
    """Raised when the Entsorgung RJ API returns an error or invalid response."""

    def __init__(self, status: int, message: str, body: str = "") -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.body = body


class ClientIdentity(NamedTuple):
    """Anonymous client credentials used to authenticate with the API."""

    anonymous_user_id: str
    device_token: str
    is_new: bool = True


@dataclass(frozen=True)
class DistrictSchedule:
    """Resolved district paired with its collection schedule window."""

    district: dict[str, Any]
    schedules: list[dict[str, Any]]
    start_date: str | None = None
    end_date: str | None = None

    @property
    def district_id(self) -> int:
        """Numeric region ID for the district."""
        return int(self.district["id"])

    @property
    def district_name(self) -> str:
        """Display name of the district (e.g. 'Kreis 2')."""
        return str(self.district["name"])


def generate_identity(
    user_id: str | None = None,
    device_token: str | None = None,
    *,
    is_new: bool = True,
) -> ClientIdentity:
    """Create a fresh anonymous client identity without touching disk."""
    uid = user_id.strip() if user_id else str(uuid.uuid4())
    tok = (device_token or f"cli-{uid}").strip()
    return ClientIdentity(anonymous_user_id=uid, device_token=tok, is_new=is_new)


def resolve_district(
    query: str | int,
    regions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match a district by numeric ID, exact name, or case-insensitive substring."""
    cleaned = str(query).strip()
    if cleaned.isdigit():
        target_id = int(cleaned)
        for region in regions:
            if region.get("id") == target_id:
                return region

    q_lower = cleaned.lower()
    for region in regions:
        if str(region.get("name", "")).strip().lower() == q_lower:
            return region

    matches = [r for r in regions if q_lower in str(r.get("name", "")).lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(f"{m['name']} (id={m['id']})" for m in matches)
        msg = f"Ambiguous district {query!r}. Matches: {names}"
        raise ValueError(msg)

    available = ", ".join(f"{r['name']} (id={r['id']})" for r in regions)
    msg = f"District {query!r} not found. Available districts: {available}"
    raise ValueError(msg)


def parse_schedule_date(item: dict[str, Any]) -> dt.date:
    """Parse the ISO-8601 `scheduled_date_time` field of a schedule item."""
    raw = str(item.get("scheduled_date_time", ""))
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(raw).date()
    except ValueError:
        return dt.date.fromisoformat(raw[:10])


def get_category_name(item: dict[str, Any]) -> str:
    """Return a displayable waste category name for a schedule item."""
    category = item.get("category")
    if isinstance(category, dict) and category.get("name"):
        return str(category["name"])
    return f"Category {item.get('category_id')}"


def filter_schedules(
    schedules: list[dict[str, Any]],
    *,
    upcoming: bool = False,
    category: str | None = None,
    today: dt.date | None = None,
) -> list[dict[str, Any]]:
    """Filter schedule items by date and category, returning them sorted by date."""
    filtered = list(schedules)

    if upcoming:
        cutoff = today or dt.datetime.now().astimezone().date()
        filtered = [s for s in filtered if parse_schedule_date(s) >= cutoff]

    if category:
        cat_query = category.strip().lower()
        filtered = [
            s
            for s in filtered
            if cat_query in str((s.get("category") or {}).get("name") or "").lower()
        ]

    return sorted(filtered, key=parse_schedule_date)
