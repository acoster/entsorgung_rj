# entsorgung_rj

Unofficial Python client and iCalendar exporter for the Rapperswil-Jona waste
collection calendar (the *Entsorgung RJ* app), plus a Cloudflare Worker that
publishes each district's calendar as a subscribable `.ics` feed and an address
lookup that tells you which district you're in.

**Just want the calendar?** Go to **<https://entsorgung-rappi.coster.li>**, pick your
district (Kreis) and subscribe. No installation needed.
Not sure which district you're in? Look up your address at
**<https://entsorgung-rappi.coster.li/kreis>**.

- **Standard library only.** No runtime dependencies, Python 3.10+.
- **CLI:** list districts and show or export a district's collection dates.
- **Library:** sync and async clients with pluggable HTTP transports.
- **Cloudflare Worker:** serves `/<district>.ics` with KV caching, so calendar
  apps can subscribe without hitting the backend on every poll.
- **Address lookup:** a static page at `/kreis` that finds the district for any
  Rapperswil-Jona address, using polygons extracted from the city's PDF map.

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

## Address lookup (`/kreis`)

The city tells you your district only through a PDF map, so
<https://entsorgung-rappi.coster.li/kreis> does the lookup for you. Type your address,
pick it from the suggestions, and the page shows your Kreis with a button that opens the
calendar page with that district selected. It is available in German and English.

It is a single static page, [`worker/public/kreis.html`](./worker/public/kreis.html), and
runs entirely in the browser:

- **Addresses** come from the [geo.admin.ch](https://www.geo.admin.ch) address search (free,
  no key). Results are limited to Rapperswil-Jona: postcodes 8640, 8645, 8646 and 8715,
  municipality number 3340. Hurden (SZ) also uses 8640, so it is excluded.
- **Districts** come from [`worker/public/kreise.geojson`](./worker/public/kreise.geojson),
  one polygon per Kreis. Addresses within 25 m of a border get a "please check the official
  map" warning, because the borders are only accurate to roughly 10–20 m.

See [worker/README.md](./worker/README.md#address-lookup-kreis) for how it is served.

## District polygons (extraction tool)

[`tools/kreise/build_kreise.py`](./tools/kreise/build_kreise.py) generates `kreise.geojson`
from the city's district map, `Abfallkreise_<year>_RJ.pdf`, linked from
<https://www.rapperswil-jona.ch/abfallkreise>:

```bash
pip install pdfplumber opencv-python-headless scipy numpy   # dev only, not needed at runtime
python tools/kreise/build_kreise.py Abfallkreise_2026_RJ.pdf -o worker/public/kreise.geojson
```

The PDF is a vector map with one coloured shape per Kreis, so the tool reads the shapes
directly instead of tracing them. It works in four steps:

1. Read the district shapes from both PDF pages.
2. Line each page up with real coordinates by fitting ~350 geocoded addresses
   ([`addresses.json`](./tools/kreise/addresses.json)) onto the map's building footprints.
   The typical miss is about 3–4 m.
3. Close gaps such as railway corridors, and let neighbouring districts overlap slightly so
   no address falls between them.
4. Write the result as GeoJSON in WGS84.

When the city publishes a new map, rerun the tool and check the borders in
[geojson.io](https://geojson.io) or QGIS before deploying.
[tools/kreise/README.md](./tools/kreise/README.md) explains the method in detail and
what to adjust if the map's colours or layout change.

## Documentation

- [USAGE.md](./USAGE.md): CLI, sync and async library usage, custom transports
- [API_NOTES.md](./API_NOTES.md): how the backend API works
- [openapi.yaml](./openapi.yaml): OpenAPI 3 description of the backend
- [worker/README.md](./worker/README.md): deploying the Worker, caching, statistics, monitoring
- [tools/kreise/README.md](./tools/kreise/README.md): how the district polygons are extracted

## Development

```bash
python3 -m unittest
```

The tests cover the library, CLI, calendar service, feed stats and monitor; they use the standard library
only. The extraction tool in `tools/kreise/` has its own dev dependencies (see above).

## Disclaimer

This is an independent project. It is not affiliated with, endorsed by, or
supported by Stadt Rapperswil-Jona or AdaptIT GmbH, who operate the official app
and backend. The district borders on the lookup page are derived from the city's map
and may be off by a few metres; the official map is authoritative. The API is undocumented and may change or break at any time. Please
use it considerately: cache results and avoid high request rates. For the official
calendar, use the city's *Entsorgung RJ* app or website.

## License

[MIT](./LICENSE)
