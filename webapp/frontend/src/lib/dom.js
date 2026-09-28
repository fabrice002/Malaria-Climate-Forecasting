/**
 * DOM helpers.
 *
 * `html` is a tagged template that escapes every interpolated value, so district
 * names and API strings can never inject markup. Anything that is already trusted
 * markup (built by another `html` call) is wrapped in `raw()` to opt out.
 */

const ESCAPES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

/** Escape a value for safe insertion into HTML text or an attribute. */
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

const RAW = Symbol('raw-html');

/** Mark a string as already-safe markup so `html` will not escape it. */
export function raw(markup) {
  return { [RAW]: String(markup ?? '') };
}

function render(value) {
  if (value == null || value === false) return '';
  if (Array.isArray(value)) return value.map(render).join('');
  if (typeof value === 'object' && RAW in value) return value[RAW];
  return escapeHtml(value);
}

/** Tagged template producing escaped HTML. */
export function html(strings, ...values) {
  return strings.reduce(
    (acc, str, i) => acc + str + (i < values.length ? render(values[i]) : ''),
    '',
  );
}

/** `document.querySelector`, throwing when the element is missing. */
export function mustFind(selector, root = document) {
  const el = root.querySelector(selector);
  if (!el) throw new Error(`Element not found: ${selector}`);
  return el;
}

/** Replace an element's content with markup produced by `html`. */
export function setHtml(el, markup) {
  el.innerHTML = markup;
}

/** A selector that will find this element again after its parent is re-rendered. */
function focusSelector(el) {
  if (!el || el === document.body) return null;
  if (el.id) return `#${CSS.escape(el.id)}`;
  // Climate cells have no id but are uniquely keyed by row and field.
  const { index, field } = el.dataset ?? {};
  if (index != null && field) return `[data-index="${index}"][data-field="${field}"]`;
  return null;
}

/**
 * Run a re-render without stealing focus from whatever the user is typing in.
 *
 * Components render by replacing innerHTML, which destroys and recreates every
 * input. Without this, a field bound to the store loses focus and caret position
 * on each keystroke — typing a district name becomes impossible.
 */
export function withFocusPreserved(update) {
  const active = document.activeElement;
  const selector = focusSelector(active);
  const start = active?.selectionStart ?? null;
  const end = active?.selectionEnd ?? null;

  update();

  if (!selector) return;
  const next = document.querySelector(selector);
  if (!next || next === document.activeElement) return;

  next.focus({ preventScroll: true });
  if (start != null && typeof next.setSelectionRange === 'function') {
    // Throws on input types that have no text selection (number, date).
    try { next.setSelectionRange(start, end); } catch { /* not a text field */ }
  }
}

/**
 * Attach a delegated listener.
 * Handlers survive re-renders because the listener sits on a stable ancestor.
 */
export function delegate(root, eventName, selector, handler) {
  root.addEventListener(eventName, (event) => {
    const match = event.target.closest(selector);
    if (match && root.contains(match)) handler(event, match);
  });
}
