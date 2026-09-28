/**
 * Toast notifications — non-fatal errors and confirmations.
 *
 * Fatal startup failures take over the screen instead (see main.js); this is for
 * everything the user can carry on despite.
 */

import { html, raw } from '../lib/dom.js';
import { store } from '../state/store.js';

let nextId = 1;

/**
 * Queue a notice.
 * @param {string} message
 * @param {'info'|'error'} tone
 * @param {number} ttlMs auto-dismiss delay; 0 keeps it until clicked
 */
export function notify(message, tone = 'info', ttlMs = 6000) {
  const id = nextId++;
  store.set((s) => ({ notices: [...s.notices, { id, message, tone }] }));
  if (ttlMs > 0) setTimeout(() => dismiss(id), ttlMs);
  return id;
}

export function dismiss(id) {
  store.set((s) => ({ notices: s.notices.filter((n) => n.id !== id) }));
}

export function renderToasts() {
  const { notices } = store.get();
  if (!notices.length) return '';
  const items = notices.map((n) => html`
    <li class="toast toast--${n.tone}" role="${n.tone === 'error' ? 'alert' : 'status'}">
      <span class="toast__msg">${n.message}</span>
      <button type="button" class="toast__close" data-dismiss="${n.id}"
              aria-label="Dismiss">&times;</button>
    </li>`).join('');
  return html`<ul class="toasts">${raw(items)}</ul>`;
}
