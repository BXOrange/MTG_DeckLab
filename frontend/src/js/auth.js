// Account session state and the one place that talks to /api/auth (PLR-9a).
//
// `apiFetch` is the central fetch wrapper (api.js uses it for every request): it
// sends the session cookie and, on unsafe methods, the session-bound CSRF token
// from GET /api/auth/me as `X-CSRF-Token` (plan §3). The session itself is an
// HttpOnly cookie the page cannot read; only the CSRF token lives here, in memory.
// Nothing is stored in localStorage.

import { getServerUrl } from './settings.js';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/** @type {{authenticated: boolean, name?: string, player_uuid?: string, csrf_token?: string}} */
let me = { authenticated: false };
let ready = false;
const listeners = new Set();

export function apiFetch(input, init = {}) {
  const method = (init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers || {});
  if (me.csrf_token && !SAFE_METHODS.has(method) && !headers.has('X-CSRF-Token')) {
    headers.set('X-CSRF-Token', me.csrf_token);
  }
  return fetch(input, { ...init, headers, credentials: 'include' }).then((response) => {
    // PLR-9b: a 401 on a data route means the session ended (expiry, logout elsewhere):
    // refresh the account state so views can show the login prompt instead of "server unreachable".
    if (response.status === 401 && me.authenticated && !String(input).includes('/api/auth/')) {
      refreshAuth();
    }
    return response;
  });
}

function setMe(next) {
  me = next && next.authenticated ? next : { authenticated: false };
  ready = true;
  for (const listener of listeners) listener(me);
}

export function getAuth() {
  return me;
}

export function isAuthReady() {
  return ready;
}

/** @param {(auth: object) => void} listener @returns {() => void} unsubscribe */
export function subscribeAuth(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function authJson(path, { method = 'GET', body } = {}) {
  let response;
  try {
    response = await apiFetch(`${getServerUrl()}/api/auth${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    return { ok: false, code: 'unreachable' };
  }
  let data = null;
  if (response.status !== 204) {
    try {
      data = await response.json();
    } catch {
      /* non-JSON body */
    }
  }
  if (!response.ok) {
    const code = data?.detail?.code || (response.status === 429 ? 'rate_limited' : `http_${response.status}`);
    return { ok: false, code, retryAfter: Number(response.headers.get('Retry-After')) || 0 };
  }
  return { ok: true, data };
}

/** Load the current account (call once at startup and after any session change). */
export async function refreshAuth() {
  const result = await authJson('/me');
  setMe(result.ok ? result.data : { authenticated: false });
  return me;
}

export const fetchPasswordPolicy = () => authJson('/policy');

export async function login(name, password) {
  const result = await authJson('/login', { method: 'POST', body: { name, password } });
  if (result.ok) setMe(result.data);
  return result;
}

export async function signup(name, password, invitation) {
  const result = await authJson('/signup', { method: 'POST', body: { name, password, invitation } });
  if (result.ok) setMe(result.data);
  return result;
}

export async function logout() {
  const result = await authJson('/logout', { method: 'POST' });
  if (result.ok) await refreshAuth();
  return result;
}

export async function logoutAll() {
  const result = await authJson('/logout-all', { method: 'POST' });
  if (result.ok) await refreshAuth();
  return result;
}

export const changePassword = (current_password, new_password) =>
  authJson('/password-change', { method: 'POST', body: { current_password, new_password } });

export const createInvitation = () => authJson('/invitations', { method: 'POST' });
export const listInvitations = () => authJson('/invitations');
export const revokeInvitation = (id) => authJson(`/invitations/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const listSessions = () => authJson('/sessions');
export const revokeSession = (id) => authJson(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });

/** Redeem an operator-issued recovery credential: replaces the password only, never signs in (PLR-9d). */
export const recoverPassword = (name, recovery_token, new_password) =>
  authJson('/recover', { method: 'POST', body: { name, recovery_token, new_password } });

/** Ask to delete the own account (password required); the server disables it and starts the grace period. */
export async function deleteAccount(password) {
  const result = await authJson('/delete-account', { method: 'POST', body: { password } });
  if (result.ok) await refreshAuth();
  return result;
}
