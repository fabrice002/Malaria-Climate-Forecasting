# Dashboard — Malaria Early-Warning System

Operator-facing frontend for the prediction API. Shows district risk on a map,
the monthly forecast chain, and the SHAP drivers behind each prediction.

Refactored from the single-file `malaria_dashboard.html` mock: the hard-coded
`DATA` blob is gone, every number now comes from the API, and the code is split
into modules with one responsibility each.

---

## ⚠️ Do not open `index.html` from disk

Double-clicking the file gives a blank page and this console error:

```
Access to script at 'file:///.../src/main.js' from origin 'null'
has been blocked by CORS policy
```

That is not a bug in the dashboard. Browsers treat every `file://` document as a
unique opaque origin and refuse to load **ES modules** from it, so `main.js` is
blocked before it runs. The dashboard must be served over HTTP. (It now detects
this and shows the instructions on screen rather than hanging on the spinner.)

## Run it — one command

From `webapp/`:

```bash
python serve_all.py
# dashboard  http://localhost:8000
# API docs   http://localhost:8000/docs
```

This mounts the dashboard under the API, so both share one origin: the default
`API_BASE` resolves by itself and CORS never enters the picture. Same arrangement
`nginx.conf` uses in production.

## Run it — two processes

If you prefer them separate:

```bash
# 1 — backend
pip install -r app/requirements.txt
uvicorn app.main:app --reload            # http://localhost:8000

# 2 — dashboard (any static server; no build step)
cd frontend
python -m http.server 5173               # http://localhost:5173
```

No configuration needed: `index.html` detects that it is being served from a port
other than 8000 and points the API base at `:8000` on the same host. Override
`globalThis.__MEWS_API_BASE__` there for any other deployment. CORS is already
open on the API for development.

### Single origin (recommended)

```bash
cd webapp
docker compose up --build
# dashboard  http://localhost:8080
# API docs   http://localhost:8000/docs
```

nginx serves the static files and proxies `/api` to the backend, so the browser
sees one origin, the default `API_BASE` just works, and CORS is not involved at
all. `nginx.conf` also sets a CSP, `X-Frame-Options` and `nosniff`.

---

## How it is organised

```
frontend/
├── index.html              shell + the only <script> tag
├── nginx.conf              production serving + /api proxy + security headers
├── Dockerfile              nginx:alpine, no build stage
├── vendor/leaflet/         Leaflet 1.9.4, vendored — no CDN dependency
├── styles/
│   ├── tokens.css          design tokens — the single source of visual truth
│   ├── base.css            reset, element defaults, spinner
│   ├── layout.css          page skeleton, responsive breakpoint
│   └── components.css      component styles, in on-screen order
└── src/
    ├── config.js           API base, map defaults, palette, climate seed
    ├── main.js             lifecycle, events, the only side effects
    ├── data/               Cameroon ADM0 + ADM1 boundaries (offline basemap)
    ├── api/
    │   ├── client.js       fetch wrapper: timeout, JSON, one ApiError type
    │   └── endpoints.js    one function per backend route
    ├── state/store.js      observable store + selectors
    ├── lib/
    │   ├── dom.js          escaping `html` tag, delegation, focus preservation
    │   └── format.js       number/date formatting, risk banding
    └── components/
        ├── mapView.js      Leaflet markers + boundaries + SVG fallback
        ├── detailPanel.js  district-month detail
        ├── shapChart.js    diverging SHAP bars
        ├── toolbar.js      status, district picker, climate inputs, legend
        └── toast.js        non-fatal notices
```

**Data flow is one-directional.** Components are pure functions of the store;
they never read each other's DOM and never call `fetch`. All side effects live in
`main.js`. Rendering is batched into one `requestAnimationFrame` per change.

**Why no framework or build step.** The dashboard is one screen with a handful of
transitions. Native ES modules mean what you edit is what runs — no `node_modules`,
no bundler, no lockfile to age. The Docker image is nginx plus 12 small files.
If this grows into a multi-route application, the module boundaries above are the
natural seams to split on.

---

## What it does

1. **Boot** — `GET /health`. If the API is down or the model bundle failed to
   load, a blocking screen explains which, and how to start the backend.
2. **Districts** — `GET /districts` supplies coordinates, population and the
   per-region alert threshold for all 197. `DEFAULT_REGION = null` opens
   nationwide; the toolbar filters by region.
3. **Stored results** — `GET /predictions/latest` paints whatever the MLOps
   pipeline has already computed for the whole country: one request instead of
   197.
4. **Load a district's own climate** — `GET /climate?district=…&end=…` pulls
   that district's real observed weather for the chosen period through the
   configured source, fills the readings table, and forecasts it immediately.
5. **Forecast** — `POST /predict` per district with the monthly climate readings.
   The first two months exist only to supply climate lags to the chain and are
   filtered out of the results view.
6. **Explain** — `GET /prediction/{id}/shap` for the visible month, cached by
   prediction id so switching tabs never refetches.

### Forecasting any district — the normal workflow

Type a district into the **District** box (typeahead over all 197), choose a
horizon and the month to forecast **ending** on, then press **Load observed
climate**. The dashboard fetches that district's real weather for that period,
shows where it came from, and scores it. **Latest** clears the month back to the
most recent one available.

**The default is the month in progress and the one ahead.** In August that means
August and September: what is happening, and what is coming. Days already
recorded come from the reanalysis; days still to come from a 16-day forecast and
then the seasonal ensemble.

Months that were not measured are badged in the readings table — `forecast` for a
fully projected month, `part forecast` for one stitched from both — because an
outlook and a record do not deserve equal weight. A month missing days is badged
too (`28/31 d`): rainfall is a sum, so a short month understates it.

The control reaches **three months past the current one**, matching
`MAX_OUTLOOK_MONTHS` in `routers/climate.py`; a static check keeps the two in
step so the picker cannot offer a month the API refuses. Ask for more and the
answer is a `422` naming the furthest month available. Backwards, the archive
reaches decades, so any past season can be replayed.

This is the answer to a real limitation of the earlier build: the climate table
was a fixed Yaoundé seed, so pressing *Run forecast* scored every district
against Yaoundé's weather. Kribi at 85 % humidity and Maroua at 18 % are not
interchangeable inputs, and a forecast built on the wrong one is meaningless.
The readings now carry visible provenance — which district, which source, which
window — because they only apply to the district they were fetched for.

The climate inputs remain **editable** for scenario work: change any cell and
press *Run forecast*. This is a forecasting tool, not a viewer of frozen numbers.

### The pre-filled numbers are real

Before any district is loaded, `CLIMATE_SEED_2026` in `config.js` holds the
**observed** Yaoundé monthly climate for Feb–Jun 2026, computed from
`data/yaounde_climate_2026_apr_jun.csv` (means for temperature, humidity,
pressure; sum for precipitation). They are *inputs* the operator can edit — never
stored predictions. Every predicted number on screen comes from a live model
call.

---

## Design decisions worth knowing

**Risk level vs P(high).** They come from different models and can disagree.
`risk_level` is derived from the regressor (predicted incidence vs threshold) and
is the authoritative alert; `risk_probability` is the classifier's own output and
leans heavily on geography. The panel footnote says so on screen, and the two are
never presented as if one validated the other.

**The "Elevated" band is presentation-only.** The model is strictly binary. A
month sitting within 15 % below the threshold is coloured amber so an operator can
see a district trending toward alert, but the API still says `Low`.
`ELEVATED_RATIO` in `config.js` controls the band.

**The basemap has three levels, and works with no network.** Raster tiles when
they are reachable — Esri's light grey canvas plus its separate place-name layer;
Cameroon's national and regional boundaries, vendored as GeoJSON in `src/data/`,
always; an inline SVG schematic only if Leaflet itself fails. Tiles are treated
as a bonus: after four consecutive errors both tile layers are dropped and the
boundaries take over, because an empty grey grid reads as "broken" while an
outline of Cameroon does not.

**Why not CARTO.** The dashboard used CARTO's `light_all` until that basemap
started requiring an API key. Without one it does not fail — it answers HTTP 200
with **"API KEY REQUIRED" stamped diagonally across every tile**, so no error
handler can catch it and the fallback never triggers. The only fix is a provider
that does not do this. Esri's grey canvas is the closest free equivalent: muted
by design, so the risk markers carry the colour. Its tiles are addressed
`{z}/{y}/{x}`, not the usual `{z}/{x}/{y}`, and stop at zoom 16 — hence
`maxNativeZoom`, which makes Leaflet upscale rather than request tiles that do
not exist. A static check keeps `nginx.conf`'s `img-src` in step with the
configured host; a mismatch there blocks every tile and looks exactly like a
provider outage.

**Leaflet is vendored, not loaded from a CDN.** It previously came from unpkg,
which made the map depend on the network, on that CDN, and on an SRI hash staying
correct. It now ships in `vendor/leaflet/` (165 KB).

**Re-renders preserve focus.** Components render by replacing `innerHTML`, which
destroys every input. `withFocusPreserved` in `lib/dom.js` restores the active
element and caret afterwards — without it, typing a district name is impossible
because each keystroke updates the store, which re-renders the toolbar.

**XSS.** The `html` tagged template in `lib/dom.js` escapes every interpolated
value. Nested markup must be wrapped in `raw()` explicitly, so injecting through a
district name or an API string is not possible by accident.

---

## Backend changes this required

The dashboard could not have worked against the original API. Three additions
were made — all additive, none altering existing behaviour or any scientific
result:

| Change | Why |
|---|---|
| `GET /districts` + `GET /districts/{name}` (new `routers/districts.py`, `schemas/district.py`) | The map needs coordinates, population and thresholds. The `districts` table already held them; nothing exposed them. |
| `GET /predictions/latest` | Paints the whole country from stored pipeline results in one request rather than 197. |
| `GET /climate` (new `routers/climate.py`) | Lets any district be forecast from its own observed weather. Reuses `app.mlops.sources` and `app.mlops.stages.features`, so the provider stays swappable and the daily→monthly aggregation is the same one training used. |
| `prediction_id` added to `MonthlyPrediction` | SHAP is keyed on a prediction id. The response previously returned one id for the whole run, so only the first month could ever be explained. |
| `/predict` now returns the **first** month's id as `prediction_id` | It previously used an unordered `.first()`, so the run id was arbitrary — a POST could report id 1 while `/predictions` reported 3 for the same run. |

Bugs surfaced during verification and fixed:

| Bug | Fix |
|---|---|
| `shap.TreeExplainer` raises `ValueError: could not convert string to float: '[5E-1]'` under `shap ≤ 0.47` + `xgboost ≥ 3.0`, so **every** SHAP request returned 500 | `services/explain.py` detects that exact failure and falls back to xgboost's own `pred_contribs=True` — the same TreeSHAP algorithm, identical values |
| `SHP_lat` / `SHP_lon` are **transposed** in `district_static.csv` — `shp_lat` holds longitude | Corrected in `routers/districts.py` with a comment. Verified against five known towns: swapping matches to ~0.06°, taking them as named is off by 7–18°. **The models are unaffected** — they consume both as anonymous features with the same convention in training and inference — but every marker would otherwise land outside Cameroon. |
| **The map always drew the SVG fallback**, even with Leaflet loaded and the network fine | `renderFallback()` set `usingFallback = true` as a side effect. A render scheduled during boot fires *before* `mount()`, takes the fallback branch because `map` is still null, and latches the flag permanently. Fixed by separating "not mounted yet" from "Leaflet failed" and making the fallback a pure renderer. This was systematic, not intermittent — the CDN, the SRI hashes and connectivity were all red herrings. |

---

## Verified

The shipped modules driven against a live API (see the harness in the session
notes; Leaflet is stubbed to record what the map actually asks for, every network
call is a real HTTP request):

| Check | Result |
|---|---|
| Pre-mount render does not latch the fallback | pass |
| Leaflet map created, SVG fallback **not** used | pass |
| Raster tile layer added | pass |
| Cameroon ADM0 + ADM1 boundaries loaded | pass (2 GeoJSON layers) |
| One marker per district | pass (197/197) |
| Every boundary region maps to a data region | pass (10/10) |
| Per-district climate → forecast | pass — Foumban, Kribi, Maroua 1, Bertoua |
| Coastal vs Sahel climate genuinely differs | pass — Kribi 85.3 % vs Maroua 74.1 % humidity |
| District typeahead + datalist list all 197 | pass |
| Provenance note names the loaded district | pass |

Backend alongside: `test_mlops.py` all checks passed; smoke test returns 197
districts, 10 regions, 0 coordinates outside Cameroon, and `/predict` + SHAP
working for districts in three different regions.

Static checks: every module parses, every relative import resolves, every named
import exists, every `mustFind` id present in `index.html`.

## Limitations

- **No authentication.** The API has a `users` table but no JWT gating; add it
  before exposing this beyond a trusted network.
- **Raster tiles still come from a CDN.** Leaflet and the boundaries are local,
  so the map works offline; the tile layer is the one remaining external request
  and is dropped automatically when it fails.
- **`GET /climate` is a live call per district.** A nationwide sweep belongs to
  the MLOps pipeline (`POST /mlops/run`), which is rate-limit aware; the browser
  path is capped at `MAX_INTERACTIVE_FORECAST`.
- **No historical trend chart.** `GET /history` is bound in `endpoints.js` and
  unused — it is the natural next component.
- **Forecasts are not persisted client-side.** Reloading re-runs the chain.
