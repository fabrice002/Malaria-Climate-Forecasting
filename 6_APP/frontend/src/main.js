/**
 * Application entry point.
 *
 * Owns the lifecycle: boot -> load districts -> forecast -> render. Components
 * are pure render functions over the store; all side effects (network, DOM
 * wiring) live here, so data flow is one-directional and easy to follow.
 */

import {
  DEFAULT_REGION, MAX_INTERACTIVE_FORECAST, CLIMATE_SEED_2026,
} from './config.js';
import { ApiError } from './api/client.js';
import {
  getHealth, listDistricts, listLatestPredictions, runForecast, getShap, getClimate,
} from './api/endpoints.js';
import { store, selectors } from './state/store.js';
import {
  html, raw, mustFind, setHtml, delegate, withFocusPreserved,
} from './lib/dom.js';
import { createMapView } from './components/mapView.js';
import { renderDetailPanel } from './components/detailPanel.js';
import { renderToolbar, renderDistrictList, renderLegend } from './components/toolbar.js';
import { renderToasts, notify, dismiss } from './components/toast.js';

// ── DOM handles ──────────────────────────────────────────────────────────────
const els = {
  toolbar: mustFind('#toolbar'),
  map: mustFind('#map'),
  legend: mustFind('#legend'),
  districtList: mustFind('#district-list'),
  panel: mustFind('#panel'),
  toasts: mustFind('#toasts'),
  boot: mustFind('#boot'),
};

const mapView = createMapView(els.map, { onSelect: selectDistrict });

// ── Rendering ────────────────────────────────────────────────────────────────
let frame = null;
function scheduleRender() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = null;
    render();
  });
}

function render() {
  withFocusPreserved(() => {
    setHtml(els.toolbar, renderToolbar());
    setHtml(els.legend, renderLegend());
    setHtml(els.districtList, renderDistrictList());
    setHtml(els.panel, renderDetailPanel());
    setHtml(els.toasts, renderToasts());
  });
  mapView.render();
}

store.subscribe(scheduleRender);

// ── Actions ──────────────────────────────────────────────────────────────────
function selectDistrict(name) {
  if (!name || name === store.get().selectedDistrict) return;
  store.set({ selectedDistrict: name, selectedMonth: 0 });
  void ensureShapForCurrentMonth();
}

function selectMonth(index) {
  store.set({ selectedMonth: index });
  void ensureShapForCurrentMonth();
}

/**
 * Fetch the SHAP explanation for the visible month, once.
 * Cached by prediction_id so switching tabs back and forth is free.
 */
async function ensureShapForCurrentMonth() {
  const month = selectors.currentMonth();
  if (!month) return;

  const id = month.prediction_id;
  const cached = store.get().shapCache[id];
  if (cached && cached.state !== 'error') return;

  store.set((s) => ({ shapCache: { ...s.shapCache, [id]: { state: 'loading' } } }));
  try {
    const data = await getShap(id, 'classifier');
    store.set((s) => ({ shapCache: { ...s.shapCache, [id]: { state: 'ready', data } } }));
  } catch (err) {
    store.set((s) => ({
      shapCache: {
        ...s.shapCache,
        [id]: { state: 'error', message: err.message ?? 'SHAP unavailable' },
      },
    }));
  }
}

/**
 * Score the current climate inputs interactively.
 *
 * Capped at MAX_INTERACTIVE_FORECAST districts: each one is a separate API call,
 * and a nationwide sweep belongs to the MLOps pipeline, not the browser. When
 * more districts are displayed, the selected one is scored — or the first N.
 */
async function runForecastForAll() {
  const { districts, readings, selectedDistrict } = store.get();
  if (!districts.length) return;
  if (!readings.some((r) => r.forecast)) {
    notify('At least one month must be marked for forecast.', 'error');
    return;
  }

  let targets = districts;
  if (districts.length > MAX_INTERACTIVE_FORECAST) {
    const selected = districts.filter((d) => d.name === selectedDistrict);
    targets = selected.length ? selected : districts.slice(0, MAX_INTERACTIVE_FORECAST);
    notify(
      `${districts.length} districts displayed; scoring ${targets.length} here. `
      + 'For the whole country run the pipeline: POST /api/v1/mlops/run',
      'info', 9000,
    );
  }

  await runForecastFor(targets);
}

/** Score an explicit set of districts against the current readings. */
async function runForecastFor(targets) {
  const { readings } = store.get();
  if (!targets.length) return;

  store.set({ pending: new Set(targets.map((d) => d.name)) });

  const settled = await Promise.allSettled(
    targets.map(async (d) => [d.name, await runForecast(d.name, readings)]),
  );

  const forecasts = { ...store.get().forecasts };
  const failures = [];

  settled.forEach((result, i) => {
    const name = targets[i].name;
    if (result.status === 'fulfilled') {
      const [, response] = result.value;
      // Keep only the months the operator asked to forecast; the leading months
      // exist purely to supply climate lags to the chain.
      const wanted = new Set(
        readings.filter((r) => r.forecast).map((r) => `${r.year}-${r.month}`),
      );
      forecasts[name] = {
        ...response,
        months: response.months.filter((m) => wanted.has(`${m.year}-${m.month}`)),
      };
    } else {
      failures.push(`${name}: ${result.reason?.message ?? 'failed'}`);
    }
  });

  store.set({ forecasts, pending: new Set(), selectedMonth: 0 });

  if (failures.length) {
    notify(`Forecast failed for ${failures.length} district(s). ${failures[0]}`, 'error', 0);
  }
  await ensureShapForCurrentMonth();
}

/**
 * Load a district's own observed climate into the forecast form.
 *
 * This is what makes the dashboard work for all 197 districts rather than for
 * whichever one the built-in seed happens to describe. The readings are replaced
 * wholesale, the district is selected, and the forecast is run straight away —
 * loading climate without scoring it would leave the screen showing numbers
 * belonging to the previous district.
 */
async function loadClimateForTarget() {
  const s = store.get();
  const name = (s.climateTarget ?? s.selectedDistrict ?? '').trim();

  if (!name) {
    notify('Choose a district first.', 'error');
    return;
  }
  const known = s.allDistricts.find((d) => d.name === name);
  if (!known) {
    notify(`"${name}" is not a known district. Pick one from the list.`, 'error');
    return;
  }

  store.set((st) => ({ pending: new Set([...st.pending, '__climate__']) }));
  try {
    const data = await getClimate(name, s.climateMonths, s.climateEnd);

    store.set({
      readings: data.readings.map((r) => ({
        year: r.year, month: r.month,
        temperature_c: r.temperature_c, humidity_pct: r.humidity_pct,
        pressure_hpa: r.pressure_hpa, precipitation_mm: r.precipitation_mm,
        forecast: r.forecast,
        // Whether the month was measured or projected, and whether every day of
        // it is present. Both change how much the number should be trusted.
        provenance: r.provenance, complete: r.complete,
        nDays: r.n_days, daysInMonth: r.days_in_month,
      })),
      climateMeta: {
        district: data.district, region: data.region,
        source: data.source, window: data.window,
        provenance: data.provenance, incomplete: data.incomplete_months ?? [],
      },
      selectedDistrict: data.district,
      selectedMonth: 0,
    });

    const scored = data.readings.filter((r) => r.forecast);
    const span = scored.length
      ? `${scored[0].year}-${String(scored[0].month).padStart(2, '0')}`
        + (scored.length > 1
          ? ` to ${scored.at(-1).year}-${String(scored.at(-1).month).padStart(2, '0')}`
          : '')
      : 'no forecastable month';
    notify(`${data.district}: ${data.source} climate loaded, forecasting ${span}.`,
           'info', 5000);
    await runForecastFor([known]);
  } catch (err) {
    const meta = store.get().climateMeta;
    notify(
      `Could not load climate for ${name}: ${err.message}`
      + (meta ? '' : ' Showing the built-in Yaounde sample instead.'),
      'error', 0);
  } finally {
    store.set((st) => {
      const pending = new Set(st.pending);
      pending.delete('__climate__');
      return { pending };
    });
  }
}

/**
 * Re-fetch after a period change, but only when there is a district to fetch for.
 *
 * On a fresh page with nothing selected there is nothing to reload; silently
 * doing nothing is right, and nagging with an error toast would be wrong.
 */
async function reloadPeriod() {
  const s = store.get();
  const name = (s.climateTarget ?? s.selectedDistrict ?? '').trim();
  if (!name || !s.allDistricts.some((d) => d.name === name)) return;
  await loadClimateForTarget();
}

/** Update one climate cell and invalidate stale results. */
function updateReading(index, field, rawValue) {
  const value = Number(rawValue);
  if (!Number.isFinite(value)) return;
  store.set((s) => {
    const readings = s.readings.map((r, i) => (i === index ? { ...r, [field]: value } : r));
    return { readings };
  });
}

// ── Event wiring (delegated, so it survives re-renders) ──────────────────────
delegate(document.body, 'click', '[data-action="run-forecast"]', () => {
  void runForecastForAll();
});

delegate(document.body, 'click', '[data-action="toggle-inputs"]', (_e, btn) => {
  const details = document.getElementById('climate-inputs');
  if (!details) return;
  details.open = !details.open;
  btn.setAttribute('aria-expanded', String(details.open));
});

delegate(document.body, 'click', '[data-district]', (_e, btn) => {
  selectDistrict(btn.dataset.district);
});

delegate(document.body, 'change', '[data-action="select-region"]', (_e, sel) => {
  void selectRegion(sel.value);
});

delegate(document.body, 'click', '[data-action="load-climate"]', () => {
  void loadClimateForTarget();
});

// `input` rather than `change`: picking from a datalist fires input immediately,
// so the chosen district is captured without waiting for a blur.
delegate(document.body, 'input', '[data-action="set-target"]', (_e, input) => {
  store.set({ climateTarget: input.value });
});

delegate(document.body, 'keydown', '[data-action="set-target"]', (e, input) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    store.set({ climateTarget: input.value });
    void loadClimateForTarget();
  }
});

// Changing the period reloads immediately. Recording the choice and waiting for
// a separate button press made the control look inert: the months on screen came
// from the readings already loaded, so nothing moved until the user guessed that
// "Load observed climate" was the thing to press.
delegate(document.body, 'change', '[data-action="set-climate-months"]', (_e, sel) => {
  store.set({ climateMonths: Number(sel.value) });
  void reloadPeriod();
});

delegate(document.body, 'change', '[data-action="set-climate-end"]', (_e, input) => {
  // An empty field means "latest available", which is what the API assumes when
  // the parameter is absent.
  store.set({ climateEnd: input.value || null });
  void reloadPeriod();
});

delegate(document.body, 'click', '[data-action="reset-climate-end"]', () => {
  store.set({ climateEnd: null });
  void reloadPeriod();
});

delegate(document.body, 'click', '[data-month-index]', (_e, btn) => {
  selectMonth(Number(btn.dataset.monthIndex));
});

delegate(document.body, 'click', '[data-dismiss]', (_e, btn) => {
  dismiss(Number(btn.dataset.dismiss));
});

delegate(document.body, 'change', '.cell-input', (_e, input) => {
  updateReading(Number(input.dataset.index), input.dataset.field, input.value);
});

// ── Boot ─────────────────────────────────────────────────────────────────────
function showFatal(message, detail) {
  els.boot.hidden = false;
  // `html` escapes interpolated values, so nested markup must be wrapped in
  // raw() — otherwise the <pre> arrives as literal text.
  const detailBlock = detail
    ? html`<pre class="boot__detail">${detail}</pre>`
    : '';
  setHtml(els.boot, html`
    <div class="boot__card">
      <h1 class="boot__title">Dashboard cannot start</h1>
      <p class="boot__msg">${message}</p>
      ${raw(detailBlock)}
      <p class="boot__hint">
        Start the API from <code>6_APP/</code>:
        <code>uvicorn app.main:app --reload</code>
      </p>
      <button type="button" class="btn btn--primary" onclick="location.reload()">
        Retry
      </button>
    </div>`);
}

async function boot() {
  store.set({ status: 'loading', readings: CLIMATE_SEED_2026.map((r) => ({ ...r })) });

  let health;
  try {
    health = await getHealth();
  } catch (err) {
    store.set({ status: 'error', error: err });
    showFatal(
      err instanceof ApiError && err.status === 0
        ? 'The API is not reachable.'
        : 'The API returned an error.',
      err.message,
    );
    return;
  }

  if (!health.models_loaded) {
    showFatal(
      'The API is running but the model bundle failed to load.',
      'Check that 6_APP/deployment_bundle/ contains the four .joblib models, '
      + 'district_static.csv and artifacts.json.',
    );
    return;
  }

  let allDistricts;
  try {
    allDistricts = await listDistricts();
  } catch (err) {
    showFatal('Could not load the district catalogue.', err.message);
    return;
  }

  const regions = [...new Set(allDistricts.map((d) => d.region))].sort();

  els.boot.hidden = true;
  store.set({
    status: 'ready',
    health,
    allDistricts,
    regions,
    region: DEFAULT_REGION,
    districts: filterByRegion(allDistricts, DEFAULT_REGION),
  });

  mapView.mount();
  render();

  // Show whatever the MLOps pipeline has already computed, for the whole
  // country, before doing any work of our own.
  await loadStoredPredictions();

  // Then replace the built-in seed with real observed climate for whichever
  // district is selected. Without this the dashboard opens on the seed's fixed
  // months and stays there, which reads as a forecast frozen in the past. The
  // seed remains the fallback if the fetch fails, so a network problem costs the
  // live period, not the whole screen.
  await reloadPeriod();
}


/** Districts belonging to a region; all of them when `region` is null. */
function filterByRegion(districts, region) {
  return region ? districts.filter((d) => d.region === region) : districts;
}


/**
 * Load the latest stored prediction per district.
 *
 * These come from the MLOps pipeline, which scores the whole country in the
 * background. Reading them is one request, versus 197 if the dashboard
 * recomputed everything itself.
 */
async function loadStoredPredictions() {
  try {
    const rows = await listLatestPredictions(store.get().region);
    const stored = {};
    const forecasts = { ...store.get().forecasts };

    for (const r of rows) {
      if (!r.has_prediction) continue;
      stored[r.district] = r;
      // Adapt to the shape the map and panel already expect.
      forecasts[r.district] = forecasts[r.district] ?? {
        district: r.district, region: r.region, population: r.population,
        created_at: null, prediction_id: r.prediction_id,
        months: [{
          prediction_id: r.prediction_id, month_index: 1,
          year: r.year, month: r.month,
          predicted_cases: r.predicted_cases,
          predicted_incidence: r.predicted_incidence,
          risk_level: r.risk_level, risk_probability: r.risk_probability,
          model_used: r.model_used, threshold: r.threshold,
        }],
      };
    }

    const s = store.get();
    const selected = s.selectedDistrict
      ?? Object.keys(stored)[0]
      ?? s.districts[0]?.name
      ?? null;

    store.set({ stored, forecasts, selectedDistrict: selected });

    const n = Object.keys(stored).length;
    if (n === 0) {
      notify('No stored predictions yet. Press "Run forecast", or run the '
             + 'pipeline: POST /api/v1/mlops/run', 'info', 9000);
    }
    await ensureShapForCurrentMonth();
  } catch (err) {
    notify(`Could not load stored predictions: ${err.message}`, 'error');
  }
}


/** Change the region filter and reload what is displayed. */
async function selectRegion(region) {
  const value = region || null;
  const s = store.get();
  if (value === s.region) return;
  store.set({
    region: value,
    districts: filterByRegion(s.allDistricts, value),
    selectedDistrict: null,
  });
  await loadStoredPredictions();
}

void boot();
