/**
 * Toolbar — service status, the forecast trigger, and the legend.
 *
 * The climate inputs are editable here: the dashboard is a forecasting tool, not
 * a viewer of frozen numbers, so the operator can adjust a month's readings and
 * re-run the chain.
 */

import { html, raw } from '../lib/dom.js';
import { store } from '../state/store.js';
import { decimal, monthLabel } from '../lib/format.js';
import { RISK_COLORS } from '../config.js';

function renderStatus(health, status) {
  if (status === 'error' || !health) {
    return html`<span class="status status--down" title="Backend unreachable">
      <span class="status__dot"></span> API offline</span>`;
  }
  if (!health.models_loaded) {
    return html`<span class="status status--warn" title="Bundle not loaded">
      <span class="status__dot"></span> Models not loaded</span>`;
  }
  return html`<span class="status status--up"
    title="${health.n_districts} districts · recursive chain ${health.recursive_chain_enabled ? 'on' : 'off'}">
    <span class="status__dot"></span> API v${health.app_version} · ${health.n_districts} districts</span>`;
}

/** A month offset from the current one, as 'YYYY-MM'. */
function monthOffset(n) {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/**
 * How far ahead the period may be set.
 *
 * Past months come from the reanalysis, the current and coming ones from a
 * forecast. The API projects at most three months past the current one, and
 * mirroring that here means the picker cannot offer a month the backend will
 * refuse. Kept in step with MAX_OUTLOOK_MONTHS in routers/climate.py.
 */
const MAX_AHEAD = 3;


export function renderToolbar() {
  const s = store.get();
  const busy = s.pending.size > 0;
  const forecastMonths = s.readings.filter((r) => r.forecast);
  const lagMonths = s.readings.filter((r) => !r.forecast);

  const rows = s.readings.map((r, i) => html`
    <tr class="${r.forecast ? '' : 'is-lag'}">
      <th scope="row">
        ${monthLabel(r.month, r.year)}
        ${r.forecast ? '' : html`<span class="tag">lag only</span>`}
        ${raw(provenanceTag(r))}
      </th>
      ${raw(['temperature_c', 'humidity_pct', 'pressure_hpa', 'precipitation_mm']
        .map((field) => html`
          <td>
            <input type="number" step="0.01" class="cell-input"
                   value="${r[field]}" data-index="${i}" data-field="${field}"
                   aria-label="${field} for ${monthLabel(r.month, r.year)}">
          </td>`).join(''))}
    </tr>`).join('');

  const withPrediction = Object.keys(s.stored ?? {}).length;
  const regionOptions = [
    html`<option value="" ${s.region ? '' : 'selected'}>All regions (${s.allDistricts.length})</option>`,
    ...s.regions.map((r) => {
      const n = s.allDistricts.filter((d) => d.region === r).length;
      return html`<option value="${r}" ${s.region === r ? 'selected' : ''}>${r} (${n})</option>`;
    }),
  ].join('');

  // Typeahead over the displayed districts. A 197-entry <select> is unusable;
  // a datalist lets the operator type three letters and land on the district.
  const target = s.climateTarget ?? s.selectedDistrict ?? '';
  const districtOptions = s.districts
    .map((d) => html`<option value="${d.name}">${d.region}</option>`)
    .join('');

  const monthOptions = [1, 2, 3, 4, 6, 12]
    .map((n) => html`<option value="${n}" ${s.climateMonths === n ? 'selected' : ''}>
      ${n} month${n === 1 ? '' : 's'}</option>`)
    .join('');

  // Blank means "the default", which the API resolves to next month.
  const defaultMonth = monthOffset(1);
  const furthest = monthOffset(MAX_AHEAD);

  const loadingClimate = s.pending.has('__climate__');

  return html`
    <div class="toolbar__row">
      ${raw(renderStatus(s.health, s.status))}
      <label class="visually-hidden" for="region-filter">Region</label>
      <select class="select" id="region-filter" data-action="select-region">
        ${raw(regionOptions)}
      </select>
      <span class="toolbar__count">
        ${s.districts.length} shown · ${withPrediction} with a forecast
      </span>
      <button type="button" class="btn btn--primary" data-action="run-forecast"
              ${busy ? 'disabled' : ''}>
        ${busy ? 'Running…' : 'Run forecast'}
      </button>
      <button type="button" class="btn" data-action="toggle-inputs"
              aria-expanded="false" aria-controls="climate-inputs">
        Climate inputs
      </button>
    </div>

    <div class="toolbar__row toolbar__row--target">
      <label class="field">
        <span class="field__label">District</span>
        <input class="input" id="climate-district" list="district-options"
               placeholder="Type a district name…" value="${target}"
               data-action="set-target" autocomplete="off">
      </label>
      <datalist id="district-options">${raw(districtOptions)}</datalist>

      <label class="field">
        <span class="field__label">Forecast</span>
        <select class="select" data-action="set-climate-months">${raw(monthOptions)}</select>
      </label>

      <label class="field">
        <span class="field__label">ending</span>
        <input class="input input--month" type="month" data-action="set-climate-end"
               value="${s.climateEnd ?? defaultMonth}" max="${furthest}"
               min="1950-01" aria-label="Last month to forecast">
      </label>

      <button type="button" class="btn btn--accent" data-action="load-climate"
              ${loadingClimate ? 'disabled' : ''}>
        ${loadingClimate ? 'Fetching…' : 'Load observed climate'}
      </button>

      <button type="button" class="btn btn--ghost" data-action="reset-climate-end"
              title="Back to the current month and the one ahead"
              ${s.climateEnd ? '' : 'disabled'}>Latest</button>

      <span class="toolbar__hint">
        Pulls that district's real weather for that period, then forecasts it.
      </span>
    </div>

    <details class="climate" id="climate-inputs">
      <summary class="climate__summary">
        ${forecastMonths.length} month${forecastMonths.length === 1 ? '' : 's'} forecast,
        ${lagMonths.length} supplying climate lags
      </summary>
      <table class="climate__table">
        <caption class="visually-hidden">Monthly climate inputs</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            <th scope="col">Temp °C</th>
            <th scope="col">Humidity %</th>
            <th scope="col">Pressure hPa</th>
            <th scope="col">Rain mm</th>
          </tr>
        </thead>
        <tbody>${raw(rows)}</tbody>
      </table>
      ${raw(renderClimateNote(s.climateMeta))}
    </details>`;
}

/**
 * Mark a month that was not measured.
 *
 * `observed` gets no badge: it is the norm, and badging everything would make
 * the exception invisible. A short month is called out separately because
 * rainfall is a sum, so missing days understate it rather than just adding
 * noise.
 */
function provenanceTag(r) {
  const bits = [];
  if (r.provenance === 'projected') {
    bits.push(html`<span class="tag tag--projected"
      title="Climate from a forecast, not a measurement">forecast</span>`);
  } else if (r.provenance === 'partly observed') {
    bits.push(html`<span class="tag tag--partial"
      title="Part measured, part forecast">part forecast</span>`);
  }
  if (r.complete === false) {
    bits.push(html`<span class="tag tag--short"
      title="${r.nDays} of ${r.daysInMonth} days present; rainfall is a sum, so it is understated"
      >${r.nDays}/${r.daysInMonth} d</span>`);
  }
  return bits.join('');
}

/**
 * Say where the loaded climate came from.
 *
 * The readings drive every forecast on screen, and they belong to exactly one
 * district — scoring a different one against them is a category error the
 * operator must be able to see, so provenance is stated rather than assumed.
 */
function renderClimateNote(meta) {
  if (!meta) {
    return html`<p class="climate__note">
      Pre-filled with observed Yaoundé climate, Feb–Jun 2026. Pick a district
      above and press <strong>Load observed climate</strong> to forecast it from
      its own weather, or edit any cell to score a scenario by hand.
    </p>`;
  }
  const projected = meta.provenance && meta.provenance !== 'observed';
  return html`<p class="climate__note climate__note--loaded">
    Climate for <strong>${meta.district}</strong> (${meta.region}) ·
    source <code>${meta.source}</code> ·
    ${meta.window.start} to ${meta.window.end}.
    ${raw(projected
      ? html`Months marked <em>forecast</em> come from a weather prediction, not
             a measurement — treat them as an outlook, not a record.`
      : 'Every month shown was measured.')}
    ${raw(meta.incomplete?.length
      ? html`Short months (${meta.incomplete.join(', ')}) understate rainfall,
             which is a sum.`
      : '')}
    The first two months supply the chain's climate lags and are not forecast.
    Edit any cell to score a variation.
  </p>`;
}

/** Map legend. Rendered into its own overlay inside the map container. */
export function renderLegend() {
  return html`
    <div class="legend" aria-label="Risk legend">
      <p class="legend__title">Predicted risk</p>
      <p class="legend__item">
        <span class="legend__dot" style="background:${RISK_COLORS.high}"></span>
        High — above threshold
      </p>
      <p class="legend__item">
        <span class="legend__dot" style="background:${RISK_COLORS.elevated}"></span>
        Elevated — near threshold
      </p>
      <p class="legend__item">
        <span class="legend__dot" style="background:${RISK_COLORS.low}"></span>
        Low
      </p>
    </div>`;
}

/** District picker rendered beneath the map. */
export function renderDistrictList() {
  const s = store.get();
  if (!s.districts.length) return '';

  const items = s.districts.map((d) => {
    const forecast = s.forecasts[d.name];
    const month = forecast?.months?.[s.selectedMonth] ?? forecast?.months?.[0];
    const value = month ? `${decimal(month.predicted_incidence)}` : '—';
    const band = month
      ? (month.predicted_incidence > month.threshold ? 'high'
        : month.predicted_incidence > month.threshold * 0.85 ? 'elevated' : 'low')
      : 'none';
    return html`
      <button type="button"
              class="dlist__item ${d.name === s.selectedDistrict ? 'is-active' : ''}"
              data-district="${d.name}">
        <span class="dlist__swatch dlist__swatch--${band}"></span>
        <span class="dlist__name">${d.name}</span>
        <span class="dlist__value">${value}</span>
      </button>`;
  }).join('');

  return html`<div class="dlist" role="group" aria-label="Districts">${raw(items)}</div>`;
}
