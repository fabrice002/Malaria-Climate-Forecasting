/**
 * Application configuration.
 *
 * Every environment-dependent value lives here. At deploy time the API base URL
 * can be overridden without touching a build step, by setting a global before
 * the module loads (see index.html) or by serving the app behind a reverse proxy
 * that maps /api to the backend — which is what nginx.conf does.
 */

/** Base URL of the FastAPI backend, including its version prefix. */
export const API_BASE =
  globalThis.__MEWS_API_BASE__ ?? `${window.location.origin}/api/v1`;

/** Abort a request after this long (ms). Model inference is CPU-bound. */
export const REQUEST_TIMEOUT_MS = 20_000;

/**
 * `GET /climate` needs far longer than the rest of the API.
 *
 * Every other endpoint answers from local state or a local model. This one calls
 * an upstream weather provider. That call is quick when it succeeds — about a
 * second — but the provider rate-limits by data volume, and on HTTP 429 the
 * backend deliberately backs off for 30 s before its first retry
 * (`app/mlops/sources/open_meteo.py`). So under any rate limiting the 20 s
 * default aborted before the retry had even begun, the dashboard kept showing
 * the built-in climate seed, and the period looked impossible to change.
 *
 * 90 s covers one back-off and retry. A second would need 120 s+, and at that
 * point the operator is better told than left waiting.
 */
export const CLIMATE_TIMEOUT_MS = 90_000;

/**
 * Map defaults — centred on Cameroon, not on a single district.
 *
 * The viewport is refit to whatever districts are actually displayed, so these
 * values only matter for the first paint before the catalogue arrives.
 */
export const MAP = Object.freeze({
  center: [7.37, 12.35],      // geographic centre of Cameroon
  zoom: 6,
  minZoom: 5,
  maxZoom: 18,

  /*
   * Esri's light grey canvas: muted by design, so the risk markers carry the
   * colour rather than competing with the basemap.
   *
   * This replaced CARTO's light_all, which now requires an API key and, without
   * one, still answers HTTP 200 — with "API KEY REQUIRED" stamped across every
   * tile. Because the response is a success, no error handler can catch it; the
   * only fix is not to use it. Note the {z}/{y}/{x} order, which is Esri's, not
   * the usual {z}/{x}/{y}.
   */
  tileUrl: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/'
           + 'World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',

  /*
   * Place names ship as a separate transparent layer. The base alone is almost
   * empty at national zoom, which costs an operator the landmarks they orient
   * by -- Douala, Maroua, Garoua. Drawn above the base and below the district
   * markers.
   */
  labelUrl: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/'
            + 'World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
  tileAttribution:
    'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ, '
    + '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',

  // The grey canvas is only published to z16. Declaring it lets Leaflet upscale
  // beyond that instead of requesting tiles that do not exist.
  maxNativeZoom: 16,
});

/**
 * Boundary-file region names -> the region names used in the data.
 *
 * `src/data/cameroon_adm1.json` comes from geoBoundaries, which labels regions
 * in English ("Far North"); `district_static.csv` uses the French-derived forms
 * the PNLP data carries ("Extreme Nord"). Without this mapping the region filter
 * could never highlight the matching polygon.
 */
export const REGION_GEO_NAMES = Object.freeze({
  'Adamaoua': 'Adamaoua',
  'Centre': 'Centre',
  'East': 'Est',
  'Far North': 'Extreme Nord',
  'Littoral': 'Littoral',
  'North': 'Nord',
  'North-West': 'Nord Ouest',
  'South': 'Sud',
  'South-West': 'Sud Ouest',
  'West': 'Ouest',
});

/**
 * Risk palette.
 *
 * `elevated` has no counterpart in the model — the classifier is strictly binary
 * (Low / High). It is a presentation-only band for months sitting just under the
 * threshold, so an operator sees a district approaching alert rather than a flat
 * "Low". `ELEVATED_RATIO` is the fraction of the threshold at which it starts.
 */
export const RISK_COLORS = Object.freeze({
  high: '#c0392b',
  elevated: '#d99a2b',
  low: '#3a7d5d',
});

export const ELEVATED_RATIO = 0.85;

/**
 * Region the dashboard opens on. `null` shows all 197 districts nationwide.
 *
 * The map always has access to every district; this only sets the initial
 * filter, which the user can change from the toolbar.
 */
export const DEFAULT_REGION = null;

/**
 * Districts scored when "Run forecast" is pressed without a selection.
 *
 * Forecasting is one API call per district, so running all 197 from the browser
 * would be slow and hammer the backend. The nationwide sweep belongs to the
 * MLOps pipeline (`POST /mlops/run`), which scores everything in the background
 * and stores the result; the dashboard then reads it from
 * `GET /predictions/latest`. This cap only limits the interactive button.
 */
export const MAX_INTERACTIVE_FORECAST = 12;

/**
 * Default climate inputs for the forecast form.
 *
 * These are the REAL observed monthly aggregates for Yaoundé, Feb–Jun 2026,
 * computed from data/yaounde_climate_2026_apr_jun.csv (means for temperature,
 * humidity and pressure; sum for precipitation). They are pre-filled so the
 * dashboard produces a meaningful forecast on first load — they are inputs the
 * user can edit, never stored predictions.
 *
 * February and March exist only to supply climate lags for the months that are
 * actually forecast; `forecast: false` keeps them out of the results view.
 */
export const CLIMATE_SEED_2026 = Object.freeze([
  { year: 2026, month: 2, temperature_c: 23.68, humidity_pct: 79.96, pressure_hpa: 933.91, precipitation_mm: 51.7,  forecast: false },
  { year: 2026, month: 3, temperature_c: 23.93, humidity_pct: 81.86, pressure_hpa: 932.61, precipitation_mm: 66.7,  forecast: false },
  { year: 2026, month: 4, temperature_c: 23.56, humidity_pct: 85.16, pressure_hpa: 933.02, precipitation_mm: 210.3, forecast: true  },
  { year: 2026, month: 5, temperature_c: 23.59, humidity_pct: 85.51, pressure_hpa: 934.69, precipitation_mm: 104.3, forecast: true  },
  { year: 2026, month: 6, temperature_c: 23.06, humidity_pct: 87.99, pressure_hpa: 936.02, precipitation_mm: 109.1, forecast: true  },
]);

/** How many SHAP drivers to show in the panel. */
export const SHAP_TOP_K = 6;
