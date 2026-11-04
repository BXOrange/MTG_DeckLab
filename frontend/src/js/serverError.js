// Text for a failed server call (VIS-24). The server answers every refusal with
// `{detail: {code, message, ...params}}`: a stable `code` plus a `message` already
// rendered in the caller's language (mtg_lang cookie, then Accept-Language, then
// German; backend/mtg_analyzer/i18n). The view's own locale key wins when one exists
// for the code (so the wording can match the surrounding UI); otherwise the server
// message is shown, and the bare code as the last resort. Returns PLAIN TEXT: callers
// keep their escapeHtml/escapeAttr exactly where they were.

import { hasTranslation, t } from './i18n.js';

//: Codes whose wording lives under a per-view key instead of `errors.<code>`.
const CODE_KEYS = {
  analysis_queue_full: 'dyn.queueFull',
  analysis_owner_limit: 'dyn.ownerLimit',
};

/**
 * @param {unknown} detail the response's `detail` (object, legacy string, or absent)
 * @param {string} [fallback] shown when the detail carries nothing usable
 * @returns {string}
 */
export function serverErrorText(detail, fallback = '') {
  if (typeof detail === 'string') return detail || fallback;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return fallback;
  const { code, message } = detail;
  const key = typeof code === 'string' ? CODE_KEYS[code] || `errors.${code}` : '';
  if (key && hasTranslation(key)) return t(key, detail);
  if (typeof message === 'string' && message) return message;
  return typeof code === 'string' && code ? code : fallback;
}
