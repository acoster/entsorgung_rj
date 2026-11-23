# entsorgung_rj

Unofficial Python client and iCalendar exporter for the Rapperswil-Jona waste
collection calendar (the *Entsorgung RJ* app), plus a Cloudflare Worker that
publishes each district's calendar as a subscribable `.ics` feed.

**Just want the calendar?** Go to **<https://entsorgung-rappi.coster.li>**, pick your
district (Kreis) and subscribe. No installation needed.

- **Standard library only.** No runtime dependencies, Python 3.10+.
- **CLI:** list districts and show or export a district's collection dates.
- **Library:** sync and async clients with pluggable HTTP transports.
- **Cloudflare Worker:** serves `/<district>.ics` with KV caching, so calendar
  apps can subscribe without hitting the backend on every poll.

## Quick start

```bash
pip install git+https://github.com/acoster/entsorgung_rj
```

```bash
entsorgung-rj --list-districts
```

```bash
entsorgung-rj "Kreis 2" --upcoming
```

```bash
entsorgung-rj 2 --ics kreis2.ics
```

Without installing, run it from a checkout with `python3 -m entsorgung_rj`.

On first run the CLI creates an anonymous client identity and caches it in
`~/.config/entsorgung_rj/client.json`.

## Calendar feed (Cloudflare Worker)

A public instance runs at <https://entsorgung-rappi.coster.li>. Subscribe to a district's
feed directly in any calendar app:

```
https://entsorgung-rappi.coster.li/2.ics                             # Kreis 2, all categories
https://entsorgung-rappi.coster.li/2.ics?categories=kehricht,papier  # only Kehricht and Papier
```

[`worker/`](./worker) contains the Python Worker behind it, which serves `GET /1.ics` …
`/8.ics`. `?categories=` takes waste category names or IDs (`/2.ics?categories=2,5` works
too). It keeps one backend identity per district and caches calendars for 4 hours.
See [worker/README.md](./worker/README.md) to deploy your own and for caching details.

## Documentation

- [USAGE.md](./USAGE.md): CLI, sync and async library usage, custom transports
- [API_NOTES.md](./API_NOTES.md): how the backend API works
- [openapi.yaml](./openapi.yaml): OpenAPI 3 description of the backend

## Development

```bash
python3 -m unittest
```

## Disclaimer

This is an independent project. It is not affiliated with, endorsed by, or
supported by Stadt Rapperswil-Jona or AdaptIT GmbH, who operate the official app
and backend. The API is undocumented and may change or break at any time. Please
use it considerately: cache results and avoid high request rates. For the official
calendar, use the city's *Entsorgung RJ* app or website.

## License

[MIT](./LICENSE)
