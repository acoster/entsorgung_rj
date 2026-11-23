# Entsorgung RJ — Cloudflare Worker

Serves the Rapperswil-Jona waste collection calendar for each district as iCalendar:

```
GET /                    # landing page (German/English): pick a district, subscribe / download / copy URL
GET /1.ics … /8.ics      # Kreis 1 … Kreis 8
GET /2.ics?categories=2,5            # only Kehricht and Papier
GET /2.ics?categories=kehricht,papier  # same, by name
```

`categories` filters the events by waste category (`WasteCategory` in
[`entsorgung_rj/models.py`](../entsorgung_rj/models.py)). It takes comma-separated IDs or
names, may be repeated (`?categories=2&categories=5`), and omitting it (or leaving it empty)
includes all categories. Unknown categories return `400`.

| ID | Name | Category |
|---|---|---|
| 1 | `karton` | Karton |
| 2 | `kehricht` | Kehricht |
| 3 | `gruengut` | Grüngut |
| 4 | `metall` | Metall |
| 5 | `papier` | Papier |

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
| `schedule:<id>` | District name, raw collection items + fetch timestamp | fresh for `CALENDAR_TTL_SECONDS` (default 4 h), kept 7 days as a fallback |

The `.ics` is rendered from `schedule:<id>` on every request, so all category filters for
a district share one cache entry and one upstream fetch.

Upstream traffic per district is therefore roughly 2 requests (`set-region-preference` +
`collection-schedule`) every 4 hours, plus a one-off `register-device`. If upstream fails,
the last cached calendar is served (`X-Calendar-Cache: stale`); with nothing cached it
returns `502`. Unknown districts return `404`.

## Usage statistics

No cookies, no third-party trackers. Two Cloudflare tools cover it:

**Landing page: Cloudflare Web Analytics.** It's cookieless and needs no consent banner.
Enable it in the Cloudflare dashboard under *Analytics & Logs → Web Analytics → Add a site*:

- On a custom domain proxied through Cloudflare, choose automatic setup. No code change is needed.
- On `*.workers.dev`, Cloudflare gives you a JS snippet with a site token. Paste it just
  before `</body>` in [`public/index.html`](./public/index.html).

**Calendar feeds: Workers Analytics Engine.** Every `GET /<id>.ics` writes one data point to
the `entsorgung_rj_feeds` dataset (`FEED_STATS` binding in `wrangler.toml`). It records
the district, category filter, a coarse calendar-client family (`apple`, `google`,
`outlook`, `browser`, …), cache state and HTTP status. It never records IPs or full user
agents; see [`entsorgung_rj/feed_stats.py`](../entsorgung_rj/feed_stats.py) for the field
layout. Writes are fire-and-forget, so a failure never affects the feed. Remove the binding
to turn stats off.

Calendar apps re-fetch subscriptions periodically, so requests per day approximate active
subscriptions. Query with the
[SQL API](https://developers.cloudflare.com/analytics/analytics-engine/sql-api/), using an
API token with *Account Analytics: Read*:

```bash
curl "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/analytics_engine/sql" \
  -H "Authorization: Bearer $API_TOKEN" \
  --data "SELECT blob1 AS district, blob2 AS categories, blob3 AS client,
                 SUM(_sample_interval) AS requests
          FROM entsorgung_rj_feeds
          WHERE timestamp > NOW() - INTERVAL '7' DAY AND blob5 = '200'
          GROUP BY district, categories, client
          ORDER BY requests DESC"
```

## Setup

```bash
cd worker
npm install
npx wrangler deploy   # creates the CACHE KV namespace on first deploy
```

Local development: `npx wrangler dev`.

The `[build]` step in `wrangler.toml` copies `../entsorgung_rj` into `src/` before each
`dev`/`deploy`, because Python Workers only bundle modules under the entry's directory.
