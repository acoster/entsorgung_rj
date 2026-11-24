"""Privacy-friendly usage stats for the `.ics` feed (pure, zero I/O).

Builds Workers Analytics Engine data points for each feed request. Nothing
identifying is recorded: no IP address, no full user agent, only the district,
the category filter, a coarse calendar-client family, the cache state, the
HTTP status and the network (ASN) and country the request came from. The ASN
mostly tells cloud fetchers (Google, Microsoft, Apple) apart from devices
polling directly over a residential ISP.

Data point layout (`dataset` configured in `worker/wrangler.toml`):

| Field     | Meaning                                                    |
|-----------|------------------------------------------------------------|
| `index1`  | district ID (sampling key)                                 |
| `blob1`   | district ID                                                |
| `blob2`   | categories: `all`, comma-separated IDs (`2,5`) or `invalid` |
| `blob3`   | client family (see `classify_client`)                      |
| `blob4`   | cache: `fresh`, `stale` or `none`                          |
| `blob5`   | HTTP status code                                           |
| `blob6`   | client ASN (`15169`), or `unknown`                         |
| `blob7`   | AS organisation (`Google LLC`), or `unknown`               |
| `blob8`   | ISO 3166-1 alpha-2 country (`CH`), or `unknown`            |
| `double1` | always 1 (sum `_sample_interval` to count requests)        |
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from entsorgung_rj.models import WasteCategory

# Ordered: first match wins. Substrings are matched case-insensitively.
_CLIENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("monitor", ("entsorgung-rj-monitor",)),
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

    Returns one of `monitor` (our own health check), `google`, `outlook`,
    `apple`, `thunderbird`, `davx5`, `browser`, `other` or `unknown`
    (no User-Agent).
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


_AS_ORG_MAX = 96  # Analytics Engine caps total blob size; AS names are short anyway


def _asn_label(asn: int | str | None) -> str:
    try:
        value = int(asn) if asn is not None else 0
    except (TypeError, ValueError):
        return "unknown"
    return str(value) if value > 0 else "unknown"


def _as_org_label(name: str | None) -> str:
    text = " ".join(name.split()) if isinstance(name, str) else ""
    return text[:_AS_ORG_MAX] if text else "unknown"


def _country_label(country: str | None) -> str:
    # Cloudflare uses ISO codes plus a few specials (`T1` = Tor, `XX` = unknown).
    code = country.strip().upper() if isinstance(country, str) else ""
    return code if code and len(code) <= 3 and code != "XX" else "unknown"


def feed_datapoint(
    *,
    district_id: int,
    categories: str,
    user_agent: str | None,
    cache: str,
    status: int,
    asn: int | str | None = None,
    as_organization: str | None = None,
    country: str | None = None,
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
            _asn_label(asn),
            _as_org_label(as_organization),
            _country_label(country),
        ],
        "doubles": [1],
    }
