"""Entsorgung RJ client and iCalendar library (stdlib-only, Cloudflare Worker-safe).

Importing this package does not touch the local filesystem or CLI modules.
For local CLI identity caching, see `entsorgung_rj.storage` and `entsorgung_rj.cli`.
"""

from entsorgung_rj.client import BASE_URL, AsyncEntsorgungClient, EntsorgungClient
from entsorgung_rj.ical import (
    ICS_PRODID,
    escape_ics_text,
    format_ics,
    format_schedule_ics,
)
from entsorgung_rj.models import (
    ApiError,
    ClientIdentity,
    DistrictSchedule,
    WasteCategory,
    filter_by_categories,
    filter_schedules,
    generate_identity,
    get_category_name,
    parse_categories,
    parse_schedule_date,
    resolve_district,
)
from entsorgung_rj.transport import (
    DEFAULT_TIMEOUT,
    AsyncTransport,
    FetchTransport,
    HttpClientTransport,
    HttpRequest,
    HttpResponse,
    SyncTransport,
)

__all__ = [
    "BASE_URL",
    "DEFAULT_TIMEOUT",
    "ICS_PRODID",
    "ApiError",
    "AsyncEntsorgungClient",
    "AsyncTransport",
    "ClientIdentity",
    "DistrictSchedule",
    "EntsorgungClient",
    "FetchTransport",
    "HttpClientTransport",
    "HttpRequest",
    "HttpResponse",
    "SyncTransport",
    "WasteCategory",
    "escape_ics_text",
    "filter_by_categories",
    "filter_schedules",
    "format_ics",
    "format_schedule_ics",
    "generate_identity",
    "get_category_name",
    "parse_categories",
    "parse_schedule_date",
    "resolve_district",
]
