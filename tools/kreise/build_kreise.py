"""Turn the city's district map PDF into `kreise.geojson` for the address lookup page.

The city publishes the waste districts only as a PDF (e.g. `Abfallkreise_2026_RJ.pdf`,
linked from https://www.rapperswil-jona.ch/abfallkreise). It is a vector map: every
Kreis is a filled path with its own CMYK colour, drawn over a rotated base map, split
over two pages at slightly different scales.

Steps:
1. Read the Kreis fills and the building footprints from both pages (pdfplumber).
2. Georeference each page with a similarity transform (shift, scale, rotation), fitted
   so the geocoded addresses in `addresses.json` land on building footprints.
3. Rasterise the Kreise onto a 2 m LV95 grid in PDF draw order (page 1 up to
   PAGE1_MAX_Y, page 2 after that), close small gaps (railway corridors), grow the
   outer edge into the lake/neighbouring land, and dilate 2 m so neighbours overlap
   instead of leaving gaps.
4. Vectorise and convert LV95 → WGS84 (swisstopo approximation formulas, ~1 m).

Expect borders to be off by roughly 10–20 m; the lookup page warns near borders.

Usage (dev-only dependencies, not needed by the library or the Worker):

    pip install pdfplumber opencv-python-headless scipy numpy
    python tools/kreise/build_kreise.py Abfallkreise_2026_RJ.pdf -o worker/public/kreise.geojson

For a new year's map, check that the colours in KREIS_COLOURS and the label pairs in
PAGE_LINK_LABELS still match (see tools/kreise/README.md).
"""

from __future__ import annotations

import argparse
import json
import pathlib

import cv2
import numpy as np
import pdfplumber
from scipy import ndimage
from scipy.optimize import minimize

HERE = pathlib.Path(__file__).resolve().parent

# CMYK fill colour of each Kreis, per page (0-based page index).
KREIS_COLOURS = {
    0: {(0.62, 0.15, 0.0, 0.0): 1, (0.5, 0.0, 0.75, 0.0): 2, (0.1, 0.8, 0.0, 0.0): 3,
        (0.0, 0.58, 1.0, 0.0): 4, (1.0, 0.6, 0.0, 0.2): 5, (0.1, 0.2, 1.0, 0.0): 6},
    1: {(0.0, 1.0, 0.47, 0.0): 8, (0.0, 0.0, 0.0, 1.0): 7, (0.1, 0.2, 1.0, 0.0): 6,
        (1.0, 0.6, 0.0, 0.2): 5, (0.62, 0.0, 0.15, 0.0): 1},
}
BUILDING_COLOUR = (0.0, 0.0, 0.0, 0.35)
# Two anchors on page 1 (collection-point markers ↔ their addresses), for the initial guess.
PAGE1_ANCHORS = [((172.5, 735.2), (1231355.5, 2706670.5)),    # ARA Langrüti ↔ Stampfstrasse 45
                 ((573.9, 557.9), (1234029.875, 2705598.5))]  # Engelhölzli ↔ Engelhölzlistrasse 26
# The same place labels on page 1 and page 2, to chain page 2's initial guess to page 1.
PAGE_LINK_LABELS = [((216, 833), (243, 70)), ((279, 837), (304, 74)), ((341, 840), (368, 84)),
                    ((434, 826), (471, 74)), ((403, 817), (444, 81))]
PAGE_WINDOWS = {0: (0, 0, 624, 840), 1: (0, 57, 624, 893)}  # map area used from each page (pt)

S = 4                                   # building mask resolution, px per pt
N0, E0 = 1232000, 2706500               # LV95 origin for the transform parameters
RES = 2.0                               # output grid resolution, m
E_MIN, N_MAX, WIDTH_M, HEIGHT_M = 2702000, 1235200, 11000, 6500


def subpaths(obj) -> list[list[tuple[float, float]]]:
    """Polygons of a pdfplumber curve, with Bézier segments sampled."""
    subs, sub, cur = [], [], None
    for cmd in obj.get("path") or []:
        op = cmd[0]
        if op == "m":
            if len(sub) > 2:
                subs.append(sub)
            sub, cur = [cmd[1]], cmd[1]
        elif op == "l":
            sub.append(cmd[1])
            cur = cmd[1]
        elif op == "c":
            p0 = np.array(cur)
            p1, p2, p3 = (np.array(p) for p in cmd[1:4])
            for t in np.linspace(0.25, 1, 4):
                pt = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3
                sub.append(tuple(pt))
            cur = cmd[3]
        elif op == "h":
            if len(sub) > 2:
                subs.append(sub)
            sub = []
    if len(sub) > 2:
        subs.append(sub)
    return subs or [obj["pts"]]


def colour(obj):
    col = obj.get("non_stroking_color")
    return tuple(round(c, 3) for c in col) if isinstance(col, (list, tuple)) else None


# ---- Transform: LV95 (N, E) <-> page (x, y), p = (x0, y0, scale, rotation) ----------
def to_page(p, ne: np.ndarray) -> np.ndarray:
    x0, y0, s, t = p
    dn, de = ne[:, 0] - N0, ne[:, 1] - E0
    return np.c_[x0 + s * (np.cos(t) * dn - np.sin(t) * de), y0 + s * (np.sin(t) * dn + np.cos(t) * de)]


def to_lv95(p, xy: np.ndarray) -> np.ndarray:
    x0, y0, s, t = p
    dx, dy = xy[:, 0] - x0, xy[:, 1] - y0
    return np.c_[(np.cos(t) * dx + np.sin(t) * dy) / s + N0, (-np.sin(t) * dx + np.cos(t) * dy) / s + E0]


def similarity(pairs) -> np.ndarray:
    """Least-squares transform from [((x, y), (N, E)), …]."""
    rows, rhs = [], []
    for (x, y), (n, e) in pairs:
        dn, de = n - N0, e - E0
        rows += [[1, 0, dn, -de], [0, 1, de, dn]]
        rhs += [x, y]
    x0, y0, a, b = np.linalg.lstsq(np.array(rows, float), np.array(rhs, float), rcond=None)[0]
    return np.array([x0, y0, np.hypot(a, b), np.arctan2(b, a)])


def building_distance(page) -> np.ndarray:
    """Distance (pt) from every pixel to the nearest building footprint."""
    mask = np.zeros((int(page.height * S), int(page.width * S)), np.uint8)
    for obj in page.curves + page.rects:
        if obj.get("fill") and colour(obj) == BUILDING_COLOUR:
            for sub in subpaths(obj):
                cv2.fillPoly(mask, [np.round(np.array(sub) * S).astype(np.int32)], 255)
    return cv2.distanceTransform(255 - mask, cv2.DIST_L2, 5) / S


def fit_page(dist: np.ndarray, points: np.ndarray, p0) -> tuple[np.ndarray, float]:
    """Refine p0 so `points` land on buildings; returns (params, median distance in pt)."""
    def sample(p):
        xy = to_page(p, points)
        xi = np.clip((xy[:, 0] * S).astype(int), 0, dist.shape[1] - 1)
        yi = np.clip((xy[:, 1] * S).astype(int), 0, dist.shape[0] - 1)
        return dist[yi, xi]

    p = np.asarray(p0, float)
    for trunc in (15, 8, 4, 2.5):  # coarse to fine, robust to points without a building
        p = minimize(lambda q: np.sum(np.minimum(sample(q), trunc) ** 2), p, method="Nelder-Mead",
                     options={"xatol": 1e-6, "fatol": 1e-6, "maxiter": 20000, "maxfev": 40000}).x
    return p, float(np.median(sample(p)))


def lv95_to_wgs84(e, n):
    y, x = (e - 2600000) / 1e6, (n - 1200000) / 1e6
    lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return lon * 100 / 36, lat * 100 / 36


def build(pdf_path: pathlib.Path, addresses: dict) -> tuple[dict, list[str]]:
    log = []
    pdf = pdfplumber.open(pdf_path)
    pts = {pg: np.array([pt for s in addresses.values() if s["page"] == pg + 1 for pt in s["points_n_e"]], float)
           for pg in (0, 1)}

    # 1-2. Georeference both pages.
    params = {}
    dist0 = building_distance(pdf.pages[0])
    params[0], med = fit_page(dist0, pts[0], similarity(PAGE1_ANCHORS))
    log.append(f"page 1: {1 / params[0][2]:.3f} m/pt, {np.degrees(params[0][3]):+.2f}°, "
               f"median miss {med:.2f} pt ≈ {med / params[0][2]:.1f} m")
    p1_labels = to_lv95(params[0], np.array([a for a, _ in PAGE_LINK_LABELS], float))
    p2_init = similarity([(b, tuple(ne)) for (_, b), ne in zip(PAGE_LINK_LABELS, p1_labels)])
    params[1], med = fit_page(building_distance(pdf.pages[1]), pts[1], p2_init)
    log.append(f"page 2: {1 / params[1][2]:.3f} m/pt, {np.degrees(params[1][3]):+.2f}°, "
               f"median miss {med:.2f} pt ≈ {med / params[1][2]:.1f} m")

    # 3. Rasterise.
    w, h = int(WIDTH_M / RES), int(HEIGHT_M / RES)

    def grid(ne):
        return np.c_[(ne[:, 1] - E_MIN) / RES, (N_MAX - ne[:, 0]) / RES]

    labels, valid = [], []
    for pg in (0, 1):
        lab, val = np.zeros((h, w), np.uint8), np.zeros((h, w), np.uint8)
        for obj in pdf.pages[pg].curves:  # stream order = draw order
            kreis = KREIS_COLOURS[pg].get(colour(obj)) if obj.get("fill") else None
            if not kreis or (obj["x1"] - obj["x0"]) * (obj["bottom"] - obj["top"]) < 1500 or obj["x0"] > 580:
                continue  # skip the legend swatches
            for sub in subpaths(obj):
                g = grid(to_lv95(params[pg], np.array(sub, float)))
                cv2.fillPoly(lab, [np.round(g * 8).astype(np.int32)], int(kreis), shift=3)
        x0, y0, x1, y1 = PAGE_WINDOWS[pg]
        win = to_lv95(params[pg], np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], float))
        cv2.fillPoly(val, [np.round(grid(win)).astype(np.int32)], 1)
        labels.append(lab)
        valid.append(val)
    lab = np.where(valid[0] == 1, labels[0], labels[1])
    lab = np.where((lab == 0) & (valid[1] == 1), labels[1], lab)

    union = cv2.morphologyEx((lab > 0).astype(np.uint8), cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    union = ndimage.binary_fill_holes(union)
    _, idx = ndimage.distance_transform_edt(lab == 0, return_indices=True)
    lab = np.where(union & (lab == 0), lab[idx[0], idx[1]], lab)        # fill 30 m gaps
    dist, idx = ndimage.distance_transform_edt(lab == 0, return_indices=True)
    lab = np.where((lab == 0) & (dist <= 50 / RES), lab[idx[0], idx[1]], lab)  # grow 50 m outward

    # 4. Vectorise.
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    features = []
    for kreis in range(1, 9):
        mask = cv2.dilate(cv2.morphologyEx((lab == kreis).astype(np.uint8), cv2.MORPH_OPEN, k3), k3)
        contours, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        polys = []
        for i, c in enumerate(contours):
            if hier[0][i][3] != -1 or cv2.contourArea(c) < 50:
                continue
            rings = [c] + [contours[j] for j in range(len(contours))
                           if hier[0][j][3] == i and cv2.contourArea(contours[j]) > 50]
            poly = []
            for ring in rings:
                a = cv2.approxPolyDP(ring, 1.0, True)[:, 0, :].astype(float)
                lon, lat = lv95_to_wgs84(E_MIN + a[:, 0] * RES, N_MAX - a[:, 1] * RES)
                coords = [[round(x, 6), round(y, 6)] for x, y in zip(lon, lat)]
                poly.append(coords + [coords[0]])
            polys.append(poly)
        if not polys:
            raise SystemExit(f"Kreis {kreis} not found — check KREIS_COLOURS")
        area = mask.sum() * RES * RES / 1e6
        log.append(f"Kreis {kreis}: {len(polys)} part(s), {area:.2f} km²")
        geom = ({"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1
                else {"type": "MultiPolygon", "coordinates": polys})
        features.append({"type": "Feature", "properties": {"kreis": kreis}, "geometry": geom})
    return {"type": "FeatureCollection", "name": f"kreise (from {pdf_path.name})", "features": features}, log


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", type=pathlib.Path, help="the city's Abfallkreise PDF")
    ap.add_argument("-o", "--output", type=pathlib.Path, default=pathlib.Path("kreise.geojson"))
    ap.add_argument("--addresses", type=pathlib.Path, default=HERE / "addresses.json")
    args = ap.parse_args()
    fc, log = build(args.pdf, json.loads(args.addresses.read_text())["streets"])
    print("\n".join(log))
    args.output.write_text(json.dumps(fc, separators=(",", ":")))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
