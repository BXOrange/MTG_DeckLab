// Frontend i18n: a cookie-backed German/English language switch. English is
// the default; German is opt-in via the language <select> on the
// "Einstellungen" tab (connectionSettingsView.js), which persists the choice
// and reloads the page so every string, label map and `toLocaleString`
// resolves consistently in one language.
//
// Shape mirrors connectionStatus.js: a module-cached current value + a Set of
// listeners + get/subscribe. The cookie is write-through persistence; the
// cached `currentLang` is the runtime source of truth (never a getCookie per
// t() call). Cookie/override conventions match settings.js
// (`window.MTG_LANG` overrides the built-in default, same idiom as
// `window.MTG_API_BASE_URL` for the server URL).
//
// Catalogs (locales/en.js, locales/de.js) are static-imported so t() is
// synchronous — it is called while views build template-literal HTML during
// first paint. Both ship on every load (tens of KB total, smaller than a
// single large view file). t() returns PLAIN TEXT and does not HTML-escape —
// callers keep their own escapeHtml/escapeAttr exactly where the German
// literal used to sit.

import { getCookie, setCookie } from './cookies.js';
import en from './locales/en.js';
import de from './locales/de.js';

const LANG_COOKIE = 'mtg_lang';
const COOKIE_MAX_AGE_DAYS = 365; // same as settings.js
const SUPPORTED = ['en', 'de'];
// Same default/override convention as settings.js's DEFAULT_SERVER_URL — set
// window.MTG_LANG before app.js loads to change the out-of-the-box language
// without a cookie. A present cookie still wins.
const DEFAULT_LANG = SUPPORTED.includes(window.MTG_LANG) ? window.MTG_LANG : 'en';

/** Endonyms — each option stays readable whatever the current UI language is,
 * so a user who landed in the wrong language can still find theirs. Never
 * translated. */
export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'de', label: 'Deutsch' },
];

const CATALOGS = { en, de };

function normalize(lang) {
  return SUPPORTED.includes(lang) ? lang : null;
}

let currentLang = normalize(getCookie(LANG_COOKIE)) || DEFAULT_LANG;
const listeners = new Set();
const warnedKeys = new Set();

// `document.documentElement` exists by the time this module (a deferred
// <script type="module"> at end of <body>) first runs.
document.documentElement.lang = currentLang;

/** @returns {'en' | 'de'} the active language (cached, no cookie read). */
export function getLang() {
  return currentLang;
}

/**
 * Persist and activate `lang`. Does NOT reload — the caller decides (the
 * settings <select> reloads after confirming). Returns the normalized lang.
 */
export function setLang(lang) {
  const next = normalize(lang);
  if (!next || next === currentLang) return currentLang;
  currentLang = next;
  setCookie(LANG_COOKIE, next, COOKIE_MAX_AGE_DAYS);
  document.documentElement.lang = next;
  for (const listener of listeners) listener(next);
  return next;
}

/** connectionStatus.js pattern. Kept for future live-preview use even though
 * the switch currently reloads. @param {(lang: string) => void} listener */
export function subscribeLang(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function interpolate(str, params) {
  if (!params) return str;
  // A missing param leaves its `{name}` token in place (visible + debuggable)
  // rather than throwing or printing "undefined".
  return str.replace(/\{(\w+)\}/g, (whole, name) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : whole,
  );
}

function lookup(key) {
  const active = CATALOGS[currentLang];
  if (active && Object.prototype.hasOwnProperty.call(active, key)) return active[key];
  // Fall back to the German source string so a half-translated en.js shows
  // real German, never a raw key, to end users.
  if (de && Object.prototype.hasOwnProperty.call(de, key)) return de[key];
  if (!warnedKeys.has(key)) {
    warnedKeys.add(key);
    // eslint-disable-next-line no-console
    console.warn(`[i18n] missing key: ${key}`);
  }
  return key;
}

/**
 * Translate `key`, interpolating `{token}` placeholders from `params`.
 * Returns plain text; never throws; never returns undefined.
 * @param {string} key
 * @param {Record<string, unknown>} [params]
 */
export function t(key, params) {
  const value = lookup(key);
  if (typeof value !== 'string') {
    // A plural object reached t() — caller should have used tPlural. Degrade
    // gracefully to the "other" form rather than rendering "[object Object]".
    return interpolate(String(value?.other ?? key), params);
  }
  return interpolate(value, params);
}

/**
 * Plural-aware translate. The catalog value is `{ one, other }` (the only
 * CLDR categories en/de need). `{count}` is auto-added to params.
 * @param {string} key
 * @param {number} count
 * @param {Record<string, unknown>} [params]
 */
export function tPlural(key, count, params) {
  const value = lookup(key);
  const merged = { count, ...(params || {}) };
  if (value && typeof value === 'object') {
    const form = count === 1 ? value.one : value.other;
    return interpolate(String(form ?? value.other ?? key), merged);
  }
  // Not a plural object (missing key fell through to the raw key, or a
  // string was mis-keyed) — still interpolate so `{count}` resolves.
  return interpolate(typeof value === 'string' ? value : key, merged);
}

function localeTag() {
  return currentLang === 'de' ? 'de-DE' : 'en-US';
}

/** Locale-aware number formatting — replaces the hardcoded
 * `toLocaleString('de-DE', …)` sites. */
export function fmtNumber(n, opts) {
  return Number(n ?? 0).toLocaleString(localeTag(), opts);
}

/** Locale-aware date/time formatting. `date` must already be a valid Date —
 * callers keep their own "unparseable input → raw string" guard. */
export function fmtDate(date, opts) {
  return date.toLocaleString(localeTag(), opts);
}

// Attributes the static shell localizes via `data-i18n-<attr>`. Extend this
// list (and it stays a cheap, explicit selector) rather than scanning every
// element's attribute names.
const I18N_ATTRS = ['title', 'aria-label', 'placeholder'];

/**
 * Localize static markup: elements carrying `data-i18n="key"` get their
 * textContent set from t(key); elements carrying `data-i18n-<attr>="key"`
 * (attr in I18N_ATTRS) get that attribute set from t(key). Also stamps
 * <html lang>. Idempotent — safe to call again after inserting more markup.
 */
export function applyStaticI18n(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  for (const attr of I18N_ATTRS) {
    root.querySelectorAll(`[data-i18n-${attr}]`).forEach((el) => {
      el.setAttribute(attr, t(el.getAttribute(`data-i18n-${attr}`)));
    });
  }
  document.documentElement.lang = currentLang;
}
