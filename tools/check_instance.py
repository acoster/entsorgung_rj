"""End-to-end health check for a deployed calendar Worker (stdlib only).

Fetches the live landing page and feeds the way a calendar app would and exits
non-zero if anything looks wrong. Run by `.github/workflows/monitor.yml`:

    python -m tools.check_instance https://entsorgung-rappi.coster.li

Checks:
* `/` serves the landing page.
* Every district feed (`/1.ics` … `/8.ics`) returns a valid calendar served from
  a fresh cache (`X-Calendar-Cache: ok`, so upstream is reachable), with at
  least one collection in the next `--horizon-days` days.
* `?categories=` filters events and names the download accordingly.
* Unknown categories return 400 and unknown districts return 404.

Requests use the `entsorgung-rj-monitor` User-Agent, which the feed stats count
as client family `monitor` so they can be excluded.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "entsorgung-rj-monitor/1.0 (+https://github.com/acoster/entsorgung_rj)"
DEFAULT_DISTRICTS = 8
DEFAULT_HORIZON_DAYS = 21
TIMEOUT = 30
RETRIES = 2  # extra attempts for 5xx / network errors, to ride out upstream blips
RETRY_DELAY = 20  # seconds

_DTSTART_RE = re.compile(r"^DTSTART;VALUE=DATE:(\d{8})$")


@dataclass
class Fetched:
    """Minimal HTTP response."""

    status: int
    headers: dict[str, str]
    body: str


@dataclass
class Event:
    """One VEVENT of a feed."""

    date: dt.date
    summary: str


@dataclass
class Report:
    """Collected check results."""

    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed.append(label)
        else:
            self.failed.append(f"{label}: {detail}" if detail else label)
        return ok


def fetch(url: str) -> Fetched:
    """GET `url`, returning HTTP errors as responses instead of raising."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", "replace")
            return Fetched(resp.status, {k.lower(): v for k, v in resp.headers.items()}, body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return Fetched(exc.code, {k.lower(): v for k, v in exc.headers.items()}, body)


def fetch_with_retries(
    url: str,
    *,
    get=fetch,
    retries: int = RETRIES,
    delay: float = RETRY_DELAY,
    sleep=time.sleep,
) -> Fetched:
    """Fetch, retrying server errors and network failures before giving up."""
    for attempt in range(retries + 1):
        last = attempt == retries
        try:
            resp = get(url)
        except (OSError, urllib.error.URLError):
            if last:
                raise
        else:
            if resp.status < 500 or last:
                return resp
        sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def parse_events(ics: str) -> list[Event]:
    """Extract all-day events (date + SUMMARY) from an iCalendar document."""
    events = []
    for block in ics.split("BEGIN:VEVENT")[1:]:
        date = None
        summary = ""
        for line in block.splitlines():
            match = _DTSTART_RE.match(line.strip())
            if match:
                date = dt.datetime.strptime(match.group(1), "%Y%m%d").date()
            elif line.startswith("SUMMARY:"):
                summary = line[len("SUMMARY:") :].strip()
        if date is not None:
            events.append(Event(date, summary))
    return events


def check_feed(
    report: Report,
    label: str,
    resp: Fetched,
    *,
    today: dt.date,
    horizon_days: int,
) -> list[Event]:
    """Validate a feed response; returns its events (empty if invalid)."""
    if not report.check(resp.status == 200, f"{label} status", f"HTTP {resp.status}"):
        return []
    ctype = resp.headers.get("content-type", "")
    report.check(ctype.startswith("text/calendar"), f"{label} content type", ctype)
    if not report.check(
        resp.body.startswith("BEGIN:VCALENDAR") and "END:VCALENDAR" in resp.body,
        f"{label} is a calendar",
        resp.body[:80].replace("\n", " "),
    ):
        return []
    cache = resp.headers.get("x-calendar-cache", "")
    report.check(
        cache == "ok",
        f"{label} fresh",
        f"X-Calendar-Cache={cache or 'missing'} (upstream failing, serving stale copy)",
    )
    events = parse_events(resp.body)
    horizon = today + dt.timedelta(days=horizon_days)
    upcoming = [e for e in events if today <= e.date <= horizon]
    report.check(
        bool(upcoming),
        f"{label} has upcoming collections",
        f"{len(events)} events, none between {today} and {horizon}",
    )
    return events


def run(
    base_url: str,
    *,
    districts: int = DEFAULT_DISTRICTS,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    today: dt.date | None = None,
    get=fetch_with_retries,
) -> Report:
    """Run every check against `base_url` and return the report."""
    base = base_url.rstrip("/")
    today = today or dt.date.today()
    report = Report()

    page = get(f"{base}/")
    report.check(
        page.status == 200 and "entsorgung" in page.body.lower(),
        "landing page",
        f"HTTP {page.status}",
    )

    for district in range(1, districts + 1):
        check_feed(
            report,
            f"/{district}.ics",
            get(f"{base}/{district}.ics"),
            today=today,
            horizon_days=horizon_days,
        )

    resp = get(f"{base}/2.ics?categories=papier")
    events = check_feed(
        report,
        "/2.ics?categories=papier",
        resp,
        today=today,
        horizon_days=366,
    )
    if events:
        others = sorted({e.summary for e in events if "papier" not in e.summary.lower()})
        report.check(not others, "category filter", f"unexpected events: {others}")
        disposition = resp.headers.get("content-disposition", "")
        report.check(
            "entsorgung-kreis-2-papier.ics" in disposition,
            "download filename",
            disposition or "missing Content-Disposition",
        )

    bad = get(f"{base}/2.ics?categories=glas")
    report.check(bad.status == 400, "unknown category rejected", f"HTTP {bad.status}")
    missing = get(f"{base}/99.ics")
    report.check(missing.status == 404, "unknown district rejected", f"HTTP {missing.status}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", help="e.g. https://entsorgung-rappi.coster.li")
    parser.add_argument("--districts", type=int, default=DEFAULT_DISTRICTS)
    parser.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)
    args = parser.parse_args(argv)

    try:
        report = run(args.base_url, districts=args.districts, horizon_days=args.horizon_days)
    except (OSError, urllib.error.URLError) as exc:
        print(f"FAIL: could not reach {args.base_url}: {exc}")
        return 1

    for label in report.passed:
        print(f"ok    {label}")
    for problem in report.failed:
        print(f"FAIL  {problem}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::error title=Instance check failed::{problem}")
    print(f"\n{len(report.passed)} passed, {len(report.failed)} failed")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
