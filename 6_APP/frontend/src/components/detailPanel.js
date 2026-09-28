/**
 * Detail panel — everything known about the selected district-month.
 *
 * Layout: district header, month tabs, risk card, key figures, the climate
 * inputs that produced the prediction, and the SHAP drivers.
 */

import { html, raw } from '../lib/dom.js';
import { store, selectors } from '../state/store.js';
import {
  int, decimal, percent, monthLabel, monthShort, riskBand, timestamp,
} from '../lib/format.js';
import { renderShapChart } from './shapChart.js';

/** Empty state before any forecast exists. */
function renderEmpty(districtName) {
  return html`
    <div class="panel__head">
      <p class="eyebrow">Health district</p>
      <h2>${districtName ?? 'No district selected'}</h2>
    </div>
    <div class="panel__body panel__empty">
      <p>No forecast for this district yet.</p>
      <p class="muted">
        Press <strong>Run forecast</strong> to score the current climate inputs
        through the model chain.
      </p>
    </div>`;
}

function renderRiskCard(month) {
  const band = riskBand(month.predicted_incidence, month.threshold);
  return html`
    <div class="riskcard riskcard--${band}">
      <div>
        <p class="riskcard__label">Risk level</p>
        <p class="riskcard__value">${month.risk_level}</p>
        ${band === 'elevated' && month.risk_level === 'Low'
          ? html`<p class="riskcard__hint">approaching threshold</p>`
          : ''}
      </div>
      <div class="riskcard__proba">
        <p class="riskcard__label">P(high)</p>
        <b>${percent(month.risk_probability)}</b>
      </div>
    </div>`;
}

function renderStats(month, district) {
  return html`
    <div class="stats">
      <div class="stat">
        <p class="stat__key">Predicted cases</p>
        <p class="stat__value">${int(month.predicted_cases)}</p>
      </div>
      <div class="stat">
        <p class="stat__key">Incidence</p>
        <p class="stat__value">${decimal(month.predicted_incidence)}<span class="stat__unit"> /1000</span></p>
      </div>
      <div class="stat">
        <p class="stat__key">Alert threshold</p>
        <p class="stat__value">${decimal(month.threshold)}<span class="stat__unit"> /1000</span></p>
      </div>
      <div class="stat">
        <p class="stat__key">Population</p>
        <p class="stat__value">${int(district?.population)}</p>
      </div>
    </div>`;
}

function renderClimate(reading) {
  if (!reading) return '';
  return html`
    <h3 class="section-title">Environmental inputs</h3>
    <div class="env">
      <div class="env__item">
        <p class="env__value">${decimal(reading.temperature_c)}°</p>
        <p class="env__label">Temp</p>
      </div>
      <div class="env__item">
        <p class="env__value">${decimal(reading.humidity_pct)}%</p>
        <p class="env__label">Humidity</p>
      </div>
      <div class="env__item">
        <p class="env__value">${decimal(reading.precipitation_mm)}</p>
        <p class="env__label">Rain mm</p>
      </div>
      <div class="env__item">
        <p class="env__value">${decimal(reading.pressure_hpa)}</p>
        <p class="env__label">hPa</p>
      </div>
    </div>`;
}

export function renderDetailPanel() {
  const s = store.get();
  const district = selectors.currentDistrict(s);
  const forecast = selectors.currentForecast(s);
  const months = selectors.currentMonths(s);

  if (s.pending.has(s.selectedDistrict)) {
    return html`
      <div class="panel__head">
        <p class="eyebrow">Health district</p>
        <h2>${s.selectedDistrict}</h2>
      </div>
      <div class="panel__body panel__empty">
        <span class="spinner" aria-hidden="true"></span>
        <p>Running the model chain…</p>
      </div>`;
  }

  if (!forecast || !months.length) return renderEmpty(s.selectedDistrict);

  const month = selectors.currentMonth(s);
  const reading = selectors.readingFor(month, s);
  const shapState = s.shapCache[month.prediction_id];

  const tabs = months.map((m, i) => html`
    <button type="button" class="mtab__btn ${i === s.selectedMonth ? 'is-active' : ''}"
            data-month-index="${i}"
            aria-pressed="${i === s.selectedMonth ? 'true' : 'false'}">
      ${monthShort(m.month)} ${m.year}
    </button>`).join('');

  return html`
    <div class="panel__head">
      <p class="eyebrow">Health district</p>
      <h2>${forecast.district}</h2>
      <p class="panel__meta">
        ${forecast.region} · Population ${int(forecast.population)}${
          // Predictions read back from /predictions/latest carry no run
          // timestamp; showing one would render the Unix epoch.
          forecast.created_at ? ` · Run ${timestamp(forecast.created_at)}` : ''}
      </p>
    </div>

    <div class="mtab" role="group" aria-label="Forecast month">${raw(tabs)}</div>

    <div class="panel__body">
      <p class="model-badge" title="Which model in the chain produced this month">
        ${monthLabel(month.month, month.year)} · ${month.model_used} model
      </p>

      ${raw(renderRiskCard(month))}
      ${raw(renderStats(month, district))}
      ${raw(renderClimate(reading))}

      <h3 class="section-title">Why this prediction — SHAP drivers</h3>
      ${raw(renderShapChart(
        shapState?.data ?? null,
        shapState?.state ?? 'loading',
        shapState?.message ?? '',
      ))}
    </div>

    <p class="panel__footnote">
      <strong>Risk level</strong> comes from predicted incidence against the
      district threshold. <strong>P(high)</strong> is the classifier's own
      probability; it leans on geography, so the two can differ. Treat the risk
      level as the alert.
    </p>`;
}
