/**
 * Endpoint bindings — one function per backend route.
 *
 * This is the frontend's view of the API contract. If a route changes, this file
 * is the only thing that needs to change. Component code calls these functions
 * and never constructs a path.
 *
 * Backend routes used (prefix /api/v1):
 *   GET  /health
 *   GET  /districts
 *   GET  /climate
 *   POST /predict
 *   GET  /prediction/{id}
 *   GET  /prediction/{id}/shap
 *   GET  /predictions
 *   GET  /predictions/latest
 *   GET  /history
 */

import { http } from './client.js';
import { CLIMATE_TIMEOUT_MS } from '../config.js';

/** Service status and whether the model bundle loaded. */
export const getHealth = () => http.get('/health');

/** All health districts with coordinates, population and threshold. */
export const listDistricts = (params) => http.get('/districts', params);

/** One district by exact name. */
export const getDistrict = (name) =>
  http.get(`/districts/${encodeURIComponent(name)}`);

/**
 * Observed monthly climate for one district, shaped for `runForecast`.
 *
 * This is what makes the dashboard usable beyond a single district: rather than
 * scoring everywhere against one hard-coded climate seed, each district can be
 * forecast from its own real weather. The backend pulls it through the MLOps
 * source layer, so the provider is whatever `MEWS_CLIMATE_SOURCE` selects.
 *
 * @param {string} district
 * @param {number} months how many months to mark forecastable (2 more are
 *                        returned to supply the chain's climate lags)
 * @param {string|null} end last month to return, as 'YYYY-MM'. Omit for the
 *                     most recent month the source can serve, which is the
 *                     previous whole one -- reanalysis lags real time by days,
 *                     so the running month would aggregate to a partial value.
 */
export const getClimate = (district, months = 3, end = null) =>
  http.get('/climate', {
    district,
    months,
    // The API takes a date; any day in the month selects that month.
    ...(end ? { end: `${end}-01` } : {}),
  }, { timeoutMs: CLIMATE_TIMEOUT_MS });

/**
 * Run the two-stage recursive chain for one district.
 * @param {string} district
 * @param {Array<object>} readings time-ordered monthly climate readings
 */
export const runForecast = (district, readings) =>
  http.post('/predict', {
    readings: readings.map((r) => ({
      district,
      year: r.year,
      month: r.month,
      temperature_c: r.temperature_c,
      humidity_pct: r.humidity_pct,
      pressure_hpa: r.pressure_hpa,
      precipitation_mm: r.precipitation_mm,
      ...(r.real_cases != null ? { real_cases: r.real_cases } : {}),
    })),
  });

/**
 * Latest stored prediction for every district — what the map consumes.
 *
 * Districts never scored come back with `has_prediction: false` so they can
 * still be placed on the map, greyed out.
 */
export const listLatestPredictions = (region) =>
  http.get('/predictions/latest', region ? { region } : undefined);

/** Full detail of a stored run. */
export const getPrediction = (predictionId) =>
  http.get(`/prediction/${predictionId}`);

/**
 * SHAP explanation for ONE forecast month.
 * @param {number} predictionId id of that month, from MonthlyPrediction
 * @param {'classifier'|'regressor'} modelKind
 */
export const getShap = (predictionId, modelKind = 'classifier') =>
  http.get(`/prediction/${predictionId}/shap`, { model_kind: modelKind });

/** Recent prediction runs. */
export const listPredictions = (limit = 20) =>
  http.get('/predictions', { limit });

/** Chronological history for one district. */
export const getHistory = (district) => http.get('/history', { district });
