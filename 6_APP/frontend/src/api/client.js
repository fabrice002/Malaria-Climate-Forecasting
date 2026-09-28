/**
 * HTTP client — the single place that talks to the network.
 *
 * Responsibilities: build URLs, enforce a timeout, parse JSON, and turn every
 * failure into one predictable `ApiError`. Nothing above this layer touches
 * `fetch`, so retry policy, auth headers or logging can be added in one place.
 */

import { API_BASE, REQUEST_TIMEOUT_MS } from '../config.js';

/** A failed API call. `status` is 0 for network/timeout failures. */
export class ApiError extends Error {
  constructor(message, { status = 0, url = '', body = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.url = url;
    this.body = body;
  }

  /** True when retrying could plausibly succeed. */
  get isRetryable() {
    return this.status === 0 || this.status >= 500;
  }
}

/** Build a full URL with optional query parameters. */
function buildUrl(path, params) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Extract the most useful message the backend offered.
 * FastAPI returns {"detail": "..."} or {"detail": [{msg, loc}, ...]}.
 */
function messageFromBody(body, fallback) {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => (d.loc ? `${d.loc.join('.')}: ${d.msg}` : d.msg))
      .join('; ');
  }
  return fallback;
}

/**
 * Perform a request.
 * @returns {Promise<any>} the parsed JSON body
 * @throws {ApiError}
 */
async function request(path, { method = 'GET', params, body, signal,
                                timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
  const url = buildUrl(path, params);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  // Honour a caller-supplied signal alongside our timeout.
  signal?.addEventListener('abort', () => controller.abort(), { once: true });

  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (cause) {
    const timedOut = cause?.name === 'AbortError';
    throw new ApiError(
      timedOut
        ? `Request timed out after ${timeoutMs / 1000}s`
        : 'Cannot reach the API. Is the backend running?',
      { url },
    );
  } finally {
    clearTimeout(timer);
  }

  const payload = response.status === 204 ? null : await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(
      messageFromBody(payload, `${response.status} ${response.statusText}`),
      { status: response.status, url, body: payload },
    );
  }
  return payload;
}

export const http = {
  get: (path, params, opts) => request(path, { ...opts, method: 'GET', params }),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
};
