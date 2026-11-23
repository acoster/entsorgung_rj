"""Privacy-friendly usage stats for the `.ics` feed (pure, zero I/O).

Builds Workers Analytics Engine data points for each feed request. Nothing
identifying is recorded: no IP address, no full user agent, only the district,
the category filter, a coarse calendar-client family, the cache state and the
HTTP status.

Data point layout (`dataset` configured in `worker/wrangler.toml`):

| Field     | Meaning                                                    |
|-----------|------------------------------------------------------------|
| `index1`  | district ID (sampling key)                                 |
| `blob1`   | district ID                                                |
| `blob2`   | categories: `all`, comma-separated IDs (`2,5`) or `invalid` |
| `blob3`   | client family (see `classify_client`)                      |
| `blob4`   | cache: `fresh`, `stale` or `none`                          |
| `blob5`   | HTTP status code                                           |
| `double1` | always 1 (sum `_sample_interval` to count requests)        |
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from entsorgung_rj.models import WasteCategory

# Ordered: first match wins. Substrings are matched case-insensitively.
_CLIENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("google", ("google-calendar-importer", "google-calendar", "googlebot")),
    ("outlook", ("outlook", "microsoft office", "microsoft exchange", "office365")),
    ("apple", ("dataaccessd", "calendaragent")),
    ("thunderbird", ("thunderbird",)),
    ("davx5", ("davx5", "icsx5")),
    ("browser", ("mozilla/",)),
)

_APPLE_PREFIXES = ("ios/", "ipados/", "macos/", "mac os x/", "mac_os_x/")


def classify_client(user_agent: str | None) -> str:
    """Map a User-Agent to a coarse client family.

    Returns one of `google`, `outlook`, `apple`, `thunderbird`, `davx5`,
    `browser`, `other` or `unknown` (no User-Agent).
    """
    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    # Apple's calendar daemons start with the OS name ("iOS/18.1 ...");
    # matching "ios/" anywhere would also catch Chrome on iOS ("CriOS/").
    if ua.startswith(_APPLE_PREFIXES):
        return "apple"
    for family, needles in _CLIENT_PATTERNS:
        if any(n in ua for n in needles):
            return family
    return "other"


def categories_label(categories: Iterable[WasteCategory] | None) -> str:
    """`all` for no filter, otherwise the category IDs in ascending order."""
    ids = sorted({int(c) for c in categories or ()})
    return ",".join(map(str, ids)) if ids else "all"


def feed_datapoint(
    *,
    district_id: int,
    categories: str,
    user_agent: str | None,
    cache: str,
    status: int,
) -> dict[str, Any]:
    """Build an Analytics Engine data point (see the module docstring)."""
    return {
        "indexes": [str(district_id)],
        "blobs": [
            str(district_id),
            categories,
            classify_client(user_agent),
            cache,
            str(status),
        ],
        "doubles": [1],
    }
