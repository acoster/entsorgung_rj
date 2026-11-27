# District polygons (`kreise.geojson`)

The address lookup ([`worker/public/kreis.html`](../../worker/public/kreis.html), served at
`/kreis`) needs the boundaries of Kreis 1–8 as polygons. The city has no API or data for
them, only a PDF map (`Abfallkreise_<year>_RJ.pdf`, linked from
<https://www.rapperswil-jona.ch/abfallkreise>).
[`build_kreise.py`](./build_kreise.py) turns that PDF into
[`worker/public/kreise.geojson`](../../worker/public/kreise.geojson).

## Regenerating

```bash
pip install pdfplumber opencv-python-headless scipy numpy   # dev only
python tools/kreise/build_kreise.py Abfallkreise_2026_RJ.pdf -o worker/public/kreise.geojson
```

It prints the fit quality per page; the 2026 map gives about 3–4 m median miss:

```
page 1: 7.125 m/pt, -2.03°, median miss 0.50 pt ≈ 3.6 m
page 2: 6.875 m/pt, +2.57°, median miss 0.50 pt ≈ 3.4 m
```

Then open the result in [geojson.io](https://geojson.io) or QGIS on top of a map and look
along the borders before deploying.

## How it works

The PDF is a vector map (InDesign). Each Kreis is a filled path with its own CMYK colour,
drawn over a base map that is rotated about 90° (page right ≈ north, page down ≈ east) and
split over two pages at slightly different scales.

1. **Extract** the Kreis fills (colours in `KREIS_COLOURS`) and the building footprints
   (grey `(0, 0, 0, 0.35)` fills) from both pages with pdfplumber.
2. **Georeference** each page with a similarity transform (shift, scale, rotation). It
   starts from two collection-point markers on page 1 (`PAGE1_ANCHORS`) and from place
   labels shown on both pages (`PAGE_LINK_LABELS`), then is refined so the ~350 geocoded
   addresses in [`addresses.json`](./addresses.json) land on building footprints.
3. **Rasterise** onto a 2 m Swiss LV95 grid in PDF draw order: page 1 up to y = 840 pt,
   page 2 after that. Gaps up to 30 m (railway corridors) are closed, the outer edge grows
   50 m into the lake and neighbouring land, so lakeside addresses still match, and
   neighbours overlap by 2 m instead of leaving gaps.
4. **Vectorise** and convert LV95 → WGS84 with swisstopo's approximation formulas (~1 m).

Borders end up roughly 10–20 m from the true line. Some streets are themselves a
border (in 2026 e.g. Busskirchstrasse between 4 and 5, St. Gallerstrasse ~156–200 between
5 and 6), so houses there can land on the wrong side. The lookup page warns within 25 m of a
border and when an address falls into two overlapping districts.

## A new year's map

- **Colours:** list the large filled paths per page and their `non_stroking_color` with
  pdfplumber, and update `KREIS_COLOURS` if they changed. The script stops if a Kreis is
  missing.
- **Layout:** if the map moved on the page, update `PAGE1_ANCHORS` (marker positions),
  `PAGE_LINK_LABELS` (the same labels on both pages; `page.extract_words()` lists them) and
  `PAGE_WINDOWS` (which part of each page to use).
- **Addresses:** `addresses.json` holds LV95 coordinates from the geo.admin.ch SearchServer
  (`…/SearchServer?searchText=<street> 8645&type=locations&origins=address&sr=2056`;
  `attrs.x` is N and `attrs.y` is E). Streets spread over the whole city work best, and
  `page` must be the PDF page each street is on.
