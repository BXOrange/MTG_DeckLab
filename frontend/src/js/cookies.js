// Minimal document.cookie helpers. No external dependency needed for the
// handful of plain-string settings this app persists client-side (see
// settings.js) — just enough get/set/remove, not a general cookie-jar.

export function getCookie(name) {
  const escaped = name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1');
  const match = document.cookie.match(new RegExp(`(?:^|; )${escaped}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function setCookie(name, value, maxAgeDays) {
  const maxAgeSeconds = Math.round(maxAgeDays * 24 * 60 * 60);
  document.cookie = `${name}=${encodeURIComponent(value)}; max-age=${maxAgeSeconds}; path=/; SameSite=Lax`;
}

/** Delete a cookie by expiring it on the app's path. */
export function removeCookie(name) {
  document.cookie = `${name}=; max-age=0; path=/; SameSite=Lax`;
}

/** Cookies earlier versions set that no longer mean anything (name-based seats, PLR-9c). */
const LEGACY_COOKIES = ['mtg_client_token'];

/** Expire the stale pre-account cookies once per page load so they stop travelling with requests. */
export function expireLegacyCookies() {
  for (const name of LEGACY_COOKIES) {
    if (getCookie(name) !== null) removeCookie(name);
  }
}
