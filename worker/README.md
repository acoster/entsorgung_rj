# Entsorgung RJ — Cloudflare Worker

Serves the Rapperswil-Jona waste collection calendar for each district as iCalendar:

```
GET /                    # landing page: pick a district, subscribe / download / copy URL
GET /1.ics … /8.ics      # Kreis 1 … Kreis 8
```

The landing page is a single static file, [`public/index.html`](./public/index.html), served
via Workers static assets. It is delivered from the edge without running the Python Worker;
any path that isn't a file (e.g. `/2.ics`) falls through to the Worker.

Subscribe to e.g. `https://entsorgung-rj.<your-subdomain>.workers.dev/2.ics` in any calendar app.

## Caching

All state lives in the `CACHE` KV namespace (logic in
[`entsorgung_rj/calendar_service.py`](../entsorgung_rj/calendar_service.py)):

| Key | Contents | Lifetime |
|---|---|---|
| `identity:<id>` | Upstream identity bound to that district (one per district, registered once) | permanent |
| `regions` | District list, used to validate IDs without calling upstream | 1 day |
| `ics:<id>` | Rendered calendar + fetch timestamp | fresh for `CALENDAR_TTL_SECONDS` (default 4 h), kept 7 days as a fallback |

Upstream traffic per district is therefore roughly 2 requests (`set-region-preference` +
`collection-schedule`) every 4 hours, plus a one-off `register-device`. If upstream fails,
the last cached calendar is served (`X-Calendar-Cache: stale`); with nothing cached it
returns `502`. Unknown districts return `404`.

## Setup

```bash
cd worker
npm install
npx wrangler deploy   # creates the CACHE KV namespace on first deploy
```

Local development: `npx wrangler dev`.

The `[build]` step in `wrangler.toml` copies `../entsorgung_rj` into `src/` before each
`dev`/`deploy`, because Python Workers only bundle modules under the entry's directory.
