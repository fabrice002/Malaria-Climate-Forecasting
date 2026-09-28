/**
 * Presentation formatting and risk banding.
 *
 * Everything the user reads as a number goes through here, so units and rounding
 * stay consistent across the map, the panel and the tooltips.
 */

import { RISK_COLORS, ELEVATED_RATIO } from '../config.js';

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const integerFmt = new Intl.NumberFormat('en-GB');
const decimalFmt = new Intl.NumberFormat('en-GB', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** 5529 -> "5,529" */
export const int = (n) => (Number.isFinite(n) ? integerFmt.format(Math.round(n)) : '—');

/** 13.4712 -> "13.47" */
export const decimal = (n) => (Number.isFinite(n) ? decimalFmt.format(n) : '—');

/** 0.764 -> "76%" */
export const percent = (n) =>
  Number.isFinite(n) ? `${Math.round(n * 100)}%` : '—';

/** Signed SHAP value: 0.665 -> "+0.67", -0.02 -> "−0.02" */
export const signed = (n) => {
  if (!Number.isFinite(n)) return '—';
  const rounded = Math.abs(n) < 0.005 ? 0 : n;
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded).toFixed(2)}`;
};

/** (5, 2026) -> "May 2026" */
export const monthLabel = (month, year) =>
  `${MONTH_NAMES[month - 1] ?? month} ${year}`;

/** (5, 2026) -> "May" */
export const monthShort = (month) => (MONTH_NAMES[month - 1] ?? '').slice(0, 3);

/** ISO timestamp -> "31 Jul 2026, 14:02" */
export const timestamp = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString('en-GB', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
};

/**
 * Presentation risk band.
 *
 * The model is strictly binary — `riskLevel` from the API is the authoritative
 * Low/High. `elevated` is a display-only band for months sitting just under the
 * threshold, so an operator can see a district trending toward alert.
 *
 * @returns {'high'|'elevated'|'low'}
 */
export function riskBand(incidence, threshold) {
  if (!Number.isFinite(incidence) || !Number.isFinite(threshold)) return 'low';
  if (incidence > threshold) return 'high';
  if (incidence > threshold * ELEVATED_RATIO) return 'elevated';
  return 'low';
}

/** Colour for a risk band. */
export const riskColor = (incidence, threshold) =>
  RISK_COLORS[riskBand(incidence, threshold)];

/** Human label for a band. */
export const riskBandLabel = (band) =>
  ({ high: 'High', elevated: 'Elevated', low: 'Low' })[band] ?? 'Low';

/** Feature names as the SHAP panel shows them. */
const FEATURE_LABELS = {
  SHP_lat: 'Latitude',
  SHP_lon: 'Longitude',
  SHP_Area: 'District area',
  cluster: 'Ecological zone',
  sin_month: 'Season (sin)',
  cos_month: 'Season (cos)',
  Temperature_C: 'Temperature',
  Humidity_pct: 'Humidity',
  Pressure_hPa: 'Pressure',
  Precipitation_mm: 'Rainfall',
  Temperature_C_lag1: 'Temperature −1m',
  Temperature_C_lag2: 'Temperature −2m',
  Humidity_pct_lag1: 'Humidity −1m',
  Humidity_pct_lag2: 'Humidity −2m',
  Precipitation_mm_lag1: 'Rainfall −1m',
  Precipitation_mm_lag2: 'Rainfall −2m',
  cases_lag1: 'Cases −1m',
  cases_lag2: 'Cases −2m',
  cases_lag3: 'Cases −3m',
  rolling_mean_3m: 'Cases 3m mean',
};

export const featureLabel = (name) => FEATURE_LABELS[name] ?? name;
