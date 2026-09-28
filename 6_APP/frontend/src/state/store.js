/**
 * Application state — a small observable store.
 *
 * One source of truth. Components subscribe and re-render on change; nothing
 * reads another component's DOM. Deliberately ~40 lines rather than a framework:
 * the dashboard has one screen and a handful of transitions.
 */

/** @typedef {'idle'|'loading'|'ready'|'error'} Status */

function createStore(initialState) {
  let state = initialState;
  const listeners = new Set();

  return {
    /** Current state (treat as immutable). */
    get: () => state,

    /**
     * Merge a patch into state and notify subscribers.
     * @param {object|((s:object)=>object)} patch
     */
    set(patch) {
      const next = typeof patch === 'function' ? patch(state) : patch;
      const candidate = { ...state, ...next };
      // Skip the notify if nothing actually changed (cheap shallow compare).
      const changed = Object.keys(next).some((k) => candidate[k] !== state[k]);
      if (!changed) return;
      state = candidate;
      listeners.forEach((fn) => fn(state));
    },

    /**
     * Subscribe to changes.
     * @returns {() => void} unsubscribe
     */
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

export const store = createStore({
  /** @type {Status} */
  status: 'idle',
  /** Fatal startup error, if any. */
  error: null,

  /** Backend /health payload. */
  health: null,

  /** @type {Array<object>} every district returned by /districts */
  allDistricts: [],

  /** @type {Array<object>} districts currently displayed (after region filter) */
  districts: [],

  /** Region filter; null = nationwide. */
  region: null,

  /** @type {Array<string>} every region name, for the filter control */
  regions: [],

  /** Stored predictions keyed by district name, from /predictions/latest. */
  stored: {},

  /** Climate readings driving the forecast (editable by the user). */
  readings: [],

  /**
   * Provenance of the readings above: which district's observed climate they
   * are, from which source and over which window. `null` means the built-in
   * seed is still loaded. The forecast is only meaningful for the district the
   * climate belongs to, so this has to be visible, not implicit.
   */
  climateMeta: null,

  /** Forecast horizon requested when loading a district's climate. */
  climateMonths: 3,

  /**
   * Last month to forecast, as 'YYYY-MM'. `null` means "the most recent month
   * the source can serve", which the API resolves to the previous whole month.
   * Setting it explicitly is what lets an operator score a past period rather
   * than always landing on the same latest month.
   */
  climateEnd: null,

  /** District chosen in the picker; may differ from the one on the map. */
  climateTarget: null,

  /** district name -> PredictionResponse */
  forecasts: {},

  /** Districts still awaiting a forecast response. */
  pending: new Set(),

  /** Currently selected district name and month index (0-based). */
  selectedDistrict: null,
  selectedMonth: 0,

  /** prediction_id -> ShapExplanation, cached so tabs don't refetch. */
  shapCache: {},

  /** Non-fatal messages surfaced as toasts. */
  notices: [],
});

/** Convenience selectors — keep derived logic out of components. */
export const selectors = {
  /** The forecast for the selected district, or null. */
  currentForecast(s = store.get()) {
    return s.selectedDistrict ? s.forecasts[s.selectedDistrict] ?? null : null;
  },

  /** Only the months the user asked to forecast, in chain order. */
  currentMonths(s = store.get()) {
    return selectors.currentForecast(s)?.months ?? [];
  },

  /** The selected month's prediction, or null. */
  currentMonth(s = store.get()) {
    const months = selectors.currentMonths(s);
    return months[s.selectedMonth] ?? months[0] ?? null;
  },

  /** District record for the selected district. */
  currentDistrict(s = store.get()) {
    return s.districts.find((d) => d.name === s.selectedDistrict) ?? null;
  },

  /** Climate reading matching a forecast month. */
  readingFor(month, s = store.get()) {
    if (!month) return null;
    return s.readings.find(
      (r) => r.year === month.year && r.month === month.month,
    ) ?? null;
  },
};
