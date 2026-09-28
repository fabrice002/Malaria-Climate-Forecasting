/**
 * SHAP driver chart — a diverging bar per feature.
 *
 * Bars are scaled against the largest absolute contribution in the set, so the
 * chart shows relative influence. Positive contributions push the prediction up
 * and sit right of the centre line; negative ones sit left.
 */

import { html, raw } from '../lib/dom.js';
import { featureLabel, signed, decimal } from '../lib/format.js';
import { SHAP_TOP_K } from '../config.js';

/**
 * @param {object|null} explanation ShapExplanation from the API
 * @param {'loading'|'ready'|'error'} state
 * @param {string} [message] error text when state === 'error'
 */
export function renderShapChart(explanation, state, message = '') {
  if (state === 'loading') {
    return html`
      <div class="shap-status" role="status">
        <span class="spinner" aria-hidden="true"></span> Computing SHAP…
      </div>`;
  }

  if (state === 'error') {
    return html`<div class="shap-status shap-status--error">${message}</div>`;
  }

  const contributions = (explanation?.contributions ?? []).slice(0, SHAP_TOP_K);
  if (!contributions.length) {
    return html`<div class="shap-status">No explanation available.</div>`;
  }

  const maxAbs = Math.max(...contributions.map((c) => Math.abs(c.shap_value))) || 1;

  const rows = contributions.map((c) => {
    const positive = c.shap_value >= 0;
    // Half the track is available on each side of the centre line.
    const width = (Math.abs(c.shap_value) / maxAbs) * 50;
    return html`
      <li class="shap-row">
        <span class="shap-row__name" title="${c.feature}">${featureLabel(c.feature)}</span>
        <span class="shap-row__track">
          <span class="shap-row__axis" aria-hidden="true"></span>
          ${raw(`<span class="shap-row__bar shap-row__bar--${positive ? 'pos' : 'neg'}"
                       style="width:${width.toFixed(2)}%"></span>`)}
        </span>
        <span class="shap-row__value ${positive ? 'is-pos' : 'is-neg'}">
          ${signed(c.shap_value)}
        </span>
      </li>`;
  });

  // `html` escapes every interpolated value, so nested markup must be wrapped in
  // raw() — otherwise the inner tags arrive as literal text.
  const summary = explanation.text_summary
    ? html`<p class="shap-summary">${explanation.text_summary}</p>`
    : '';

  return html`
    <ul class="shap-list">${raw(rows.join(''))}</ul>
    <p class="shap-note">
      Baseline ${decimal(explanation.base_value)} · red increases risk, blue reduces it.
    </p>
    ${raw(summary)}`;
}
