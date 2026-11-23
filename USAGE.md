# `entsorgung_rj` — Usage Guide

`entsorgung_rj` is a Python 3 standard-library-only client and iCalendar generator for the Rapperswil-Jona waste collection schedule API. For details on the backend endpoints and protocol, see [API_NOTES.md](./API_NOTES.md) and [openapi.yaml](./openapi.yaml).

## Package Layout

Importing `entsorgung_rj` is filesystem-free and safe to use in serverless runtimes such as Cloudflare Python Workers (Pyodide):

| Module | Purpose |
|---|---|
| `entsorgung_rj.models` | Pure data models (`ClientIdentity`, `DistrictSchedule`, `ApiError`) and filtering/parsing helpers |
| `entsorgung_rj.transport` | Pluggable `SyncTransport` (`HttpClientTransport`) and `AsyncTransport` (`FetchTransport`) |
| `entsorgung_rj.client` | Sync (`EntsorgungClient`) and async (`AsyncEntsorgungClient`) API clients |
| `entsorgung_rj.ical` | Pure RFC 5545 `.ics` calendar serialization (`format_ics`, `format_schedule_ics`) |
| `entsorgung_rj.calendar_service` | KV-cached per-district `.ics` service used by the Cloudflare Worker (`DistrictCalendarService`) |
| `entsorgung_rj.formatters` | Terminal table and JSON output formatters |
| `entsorgung_rj.storage` | Local `~/.config/entsorgung_rj/client.json` identity cache (CLI / local only) |
| `entsorgung_rj.cli` | Command-line interface (`python3 -m entsorgung_rj`) |

---

## 1. Command-Line Interface (CLI)

Run the package directly as a module. On first run, an anonymous client identity is automatically generated, registered, and cached at `~/.config/entsorgung_rj/client.json`.

```bash
# List all available Rapperswil-Jona districts
python3 -m entsorgung_rj --list-districts
python3 -m entsorgung_rj --list-districts --json

# Fetch the collection calendar by district name, substring, or numeric ID
python3 -m entsorgung_rj "Kreis 2"
python3 -m entsorgung_rj 5 --upcoming
python3 -m entsorgung_rj 5 --category Papier

# Export as JSON or iCalendar (.ics)
python3 -m entsorgung_rj "Kreis 3" --json
python3 -m entsorgung_rj "Kreis 3" --ics kreis3.ics
python3 -m entsorgung_rj "Kreis 3" --ics -  # write .ics to stdout
```

### Identity Overrides

You can override the cached credentials via flags or environment variables:

```bash
ENTSORGUNG_RJ_USER_ID="<uuid>" ENTSORGUNG_RJ_TOKEN="<token>" python3 -m entsorgung_rj "Kreis 2"
python3 -m entsorgung_rj "Kreis 2" --user-id "<uuid>" --token "<token>"
```

---

## 2. Synchronous Python Library

Use `EntsorgungClient` (backed by stdlib `http.client` via `HttpClientTransport`) in scripts, cron jobs, or traditional web backends.

### Ephemeral identity (no filesystem access)

```python
from entsorgung_rj import EntsorgungClient, format_schedule_ics, generate_identity

client = EntsorgungClient(generate_identity())
schedule = client.get_district_schedule("Kreis 2", upcoming=True)

print(schedule.district_name, len(schedule.schedules))
ics_text = format_schedule_ics(schedule)
```

### Reusing the local cached identity

```python
from entsorgung_rj import EntsorgungClient
from entsorgung_rj.formatters import format_table
from entsorgung_rj.storage import load_or_create_identity

identity = load_or_create_identity()
client = EntsorgungClient(identity)
schedule = client.get_district_schedule(2, category="Papier")

print(
    format_table(
        schedule.district_name,
        schedule.schedules,
        start_date=schedule.start_date,
        end_date=schedule.end_date,
    )
)
```

### Low-level API calls

```python
from entsorgung_rj import EntsorgungClient, generate_identity

client = EntsorgungClient(generate_identity())
client.register_device()
regions = client.get_regions()
client.set_region(2)
raw_schedule = client.get_schedules()
```

---

## 3. Cloudflare Python Worker (Async)

`AsyncEntsorgungClient` defaults to `FetchTransport`, which automatically uses `workers.fetch` in Cloudflare Python Workers (and falls back to `pyodide.http.pyfetch` in Pyodide).

```python
from workers import Response, WorkerEntrypoint

from entsorgung_rj import (
    ApiError,
    AsyncEntsorgungClient,
    format_schedule_ics,
    generate_identity,
)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        district = request.url.rsplit("/", 1)[-1].removesuffix(".ics")
        client = AsyncEntsorgungClient(generate_identity())
        try:
            schedule = await client.get_district_schedule(district, upcoming=True)
        except ValueError as exc:
            return Response(str(exc), status=404)
        except ApiError as exc:
            return Response(str(exc), status=502)

        return Response(
            format_schedule_ics(schedule),
            headers={
                "Content-Type": "text/calendar; charset=utf-8",
                "Cache-Control": "public, max-age=3600",
            },
        )
```

> **Concurrency note:** The upstream backend stores the active district server-side per `device-token`. In a Worker serving multiple districts concurrently, avoid sharing a single `ClientIdentity` across requests for different districts—either generate a fresh identity per request (`generate_identity()`) or maintain a separate cached identity per district (e.g. in KV) so concurrent `set-region-preference` calls cannot overwrite each other.

### Ready-made deployment: `worker/`

The [`worker/`](./worker) directory contains a deployable Worker that serves `GET /<district-id>.ics` (e.g. `/2.ics` for *Kreis 2*). It uses `entsorgung_rj.calendar_service.DistrictCalendarService` with Workers KV to keep **one long-lived identity per district**, cache the regions list for a day, and cache each rendered calendar for 4 hours (serving the last good copy if the backend is down). See [worker/README.md](./worker/README.md) for setup.

---

## 4. Custom HTTP Transports (e.g. `httpx` or Tests)

Both clients accept any object implementing `SyncTransport` or `AsyncTransport` (`send(request: HttpRequest) -> HttpResponse`), making it straightforward to plug in `httpx`, `aiohttp`, `requests`, or in-memory test doubles.

### Custom `AsyncTransport` with `httpx`

```python
import httpx

from entsorgung_rj import (
    AsyncEntsorgungClient,
    HttpRequest,
    HttpResponse,
    generate_identity,
)


class HttpxAsyncTransport:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    async def send(self, request: HttpRequest) -> HttpResponse:
        resp = await self._client.request(
            request.method,
            request.url,
            headers=request.headers,
            content=request.body,
            timeout=request.timeout,
        )
        return HttpResponse(
            status=resp.status_code,
            reason=resp.reason_phrase,
            body=resp.text,
        )


async with httpx.AsyncClient() as http_client:
    client = AsyncEntsorgungClient(
        generate_identity(),
        transport=HttpxAsyncTransport(http_client),
    )
    schedule = await client.get_district_schedule("Kreis 2")
```

### Custom `fetch` function with `FetchTransport`

You can also inject any `fetch`-compatible coroutine directly into `FetchTransport(fetch_fn=...)` for testing or custom runtimes.

---

## 5. Formatting & iCalendar Customization

```python
import datetime as dt

from entsorgung_rj import format_ics, format_schedule_ics
from entsorgung_rj.formatters import format_districts, format_schedule_json, format_table

# Custom calendar name / PRODID / deterministic DTSTAMP
ics = format_schedule_ics(
    schedule,
    cal_name="Rapperswil-Jona Kreis 2",
    prodid="-//My Worker//Entsorgung RJ//EN",
    now=dt.datetime(2026, 11, 22, 12, 0, tzinfo=dt.timezone.utc),
)

# Or format raw schedule items directly
ics = format_ics("Kreis 2", schedule.schedules)

# Terminal & JSON formatters
table_text = format_table(schedule.district_name, schedule.schedules)
json_text = format_schedule_json(schedule)
districts_text = format_districts(regions)
```
