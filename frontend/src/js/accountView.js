// Account panel inside "Profil" (PLR-9a): login, signup by invitation token, password
// change with the red/yellow/green meter, invitations and logout. Plan:
// docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md. All user/server text goes through escapeHtml/t().

import {
  getAuth,
  subscribeAuth,
  login,
  signup,
  logout,
  logoutAll,
  changePassword,
  createInvitation,
  listInvitations,
  revokeInvitation,
  fetchPasswordPolicy,
} from './auth.js';
import { passwordStrength } from './passwordStrength.js';
import { escapeHtml } from './cardTile.js';
import { escapeAttr } from './gameSetup.js';
import { t } from './i18n.js';

// Fallback until GET /api/auth/policy answers; the server value wins.
const DEFAULT_POLICY = { min_length: 10, green_length: 12 };

/** Invitation token from a shared link (`#invite=...`): the fragment never reaches the server. */
function inviteFromHash() {
  const match = /(?:^|[#&])invite=([^&]+)/.exec(window.location.hash);
  return match ? decodeURIComponent(match[1]) : '';
}

const KNOWN_ERRORS = new Set([
  'unreachable', 'rate_limited', 'invalid_credentials', 'invalid_invitation', 'name_taken', 'invalid_name',
  'password_too_short', 'password_blocklisted', 'password_too_long', 'invitation_limit', 'csrf', 'unauthenticated',
]);

function errorText(code, retryAfter = 0) {
  const message = t(KNOWN_ERRORS.has(code) ? `account.error.${code}` : 'account.error.generic');
  return retryAfter ? `${message} (${retryAfter}s)` : message;
}

function meterHtml(id) {
  return `<div class="pw-meter" id="${id}" data-level="none" aria-live="polite">
    <span class="pw-meter-bar"><span class="pw-meter-fill"></span></span>
    <span class="pw-meter-label"></span>
  </div>`;
}

function paintMeter(meter, password, policy) {
  const label = meter.querySelector('.pw-meter-label');
  if (!password) {
    meter.dataset.level = 'none';
    label.textContent = '';
    return null;
  }
  const strength = passwordStrength(password, policy);
  meter.dataset.level = strength.level;
  const missing = strength.missing.map((m) => t(`account.pw.missing.${m}`)).join(', ');
  label.textContent =
    strength.level === 'red'
      ? t('account.pw.red', { min: policy.min_length })
      : strength.level === 'yellow'
        ? t('account.pw.yellow', { missing })
        : t('account.pw.green');
  return strength;
}

export function renderAccountPanel(container) {
  let policy = DEFAULT_POLICY;
  fetchPasswordPolicy().then((result) => {
    if (result.ok) policy = { ...DEFAULT_POLICY, ...result.data };
  });

  function renderLoggedOut() {
    const invite = inviteFromHash();
    container.innerHTML = `
      <div class="deck-section account-panel">
        <h3>${t('account.heading')}</h3>
        <p class="hint">${t('account.loggedOut')}</p>
        <div class="account-tabs" role="tablist">
          <button type="button" class="account-tab ${invite ? '' : 'active'}" data-mode="login">${t('account.login')}</button>
          <button type="button" class="account-tab ${invite ? 'active' : ''}" data-mode="signup">${t('account.signup')}</button>
        </div>
        <form id="account-form" autocomplete="on" novalidate>
          <div class="mp-option-row"><label for="account-name">${t('account.name')}</label>
            <input id="account-name" name="username" type="text" autocomplete="username" maxlength="64" required /></div>
          <div class="mp-option-row" data-signup-only hidden><label for="account-invite">${t('account.invitation')}</label>
            <input id="account-invite" type="text" autocomplete="off" spellcheck="false" value="${escapeAttr(invite)}" /></div>
          <div class="mp-option-row"><label for="account-password">${t('account.password')}</label>
            <input id="account-password" name="password" type="password" maxlength="1024" required /></div>
          <div data-signup-only hidden>${meterHtml('account-meter')}<p class="hint">${t('account.pw.hint', { min: policy.min_length })}</p></div>
          <div class="import-actions"><button type="submit" class="primary" id="account-submit">${t('account.login')}</button></div>
          <p class="account-error" id="account-error" role="alert" hidden></p>
        </form>
      </div>`;
    const form = container.querySelector('#account-form');
    const nameInput = container.querySelector('#account-name');
    const passwordInput = container.querySelector('#account-password');
    const meter = container.querySelector('#account-meter');
    const submit = container.querySelector('#account-submit');
    const error = container.querySelector('#account-error');
    const signupOnly = container.querySelectorAll('[data-signup-only]');
    let mode = invite ? 'signup' : 'login';

    function applyMode() {
      signupOnly.forEach((el) => {
        el.hidden = mode !== 'signup';
      });
      container.querySelectorAll('.account-tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.mode === mode));
      submit.textContent = mode === 'signup' ? t('account.signup') : t('account.login');
      passwordInput.autocomplete = mode === 'signup' ? 'new-password' : 'current-password';
      update();
    }
    function update() {
      const strength = paintMeter(meter, passwordInput.value, policy);
      // Red blocks submitting a new password; yellow does not (plan §3).
      submit.disabled = mode === 'signup' && (!strength || strength.level === 'red');
    }
    container.querySelectorAll('.account-tab').forEach((tab) =>
      tab.addEventListener('click', () => {
        mode = tab.dataset.mode;
        error.hidden = true;
        applyMode();
      }),
    );
    passwordInput.addEventListener('input', update);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      error.hidden = true;
      submit.disabled = true;
      const name = nameInput.value;
      const password = passwordInput.value;
      const result =
        mode === 'signup'
          ? await signup(name, password, container.querySelector('#account-invite').value.trim())
          : await login(name, password);
      if (!result.ok) {
        error.textContent = errorText(result.code, result.retryAfter);
        error.hidden = false;
        update();
        return;
      }
      if (mode === 'signup' && inviteFromHash()) history.replaceState(null, '', window.location.pathname + window.location.search);
    });
    applyMode();
  }

  function renderLoggedIn(auth) {
    container.innerHTML = `
      <div class="deck-section account-panel">
        <h3>${t('account.heading')}</h3>
        <p>${t('account.signedInAs')} <strong>${escapeHtml(auth.name)}</strong></p>
        <div class="import-actions">
          <button type="button" id="account-logout">${t('account.logout')}</button>
          <button type="button" id="account-logout-all">${t('account.logoutAll')}</button>
        </div>

        <h4>${t('account.changePassword')}</h4>
        <form id="account-pw-form" autocomplete="off" novalidate>
          <div class="mp-option-row"><label for="account-pw-current">${t('account.pw.current')}</label>
            <input id="account-pw-current" type="password" autocomplete="current-password" maxlength="1024" /></div>
          <div class="mp-option-row"><label for="account-pw-new">${t('account.pw.new')}</label>
            <input id="account-pw-new" type="password" autocomplete="new-password" maxlength="1024" /></div>
          ${meterHtml('account-pw-meter')}
          <div class="import-actions"><button type="submit" id="account-pw-submit" disabled>${t('account.changePassword')}</button></div>
          <p class="account-error" id="account-pw-message" role="status" hidden></p>
        </form>

        <h4>${t('account.invitations.heading')}</h4>
        <p class="hint">${t('account.invitations.hint')}</p>
        <div class="import-actions"><button type="button" id="account-invite-create">${t('account.invitations.create')}</button></div>
        <div id="account-invite-new" hidden></div>
        <ul id="account-invite-list" class="account-invite-list"></ul>
        <p class="account-error" id="account-invite-error" role="alert" hidden></p>
      </div>`;

    container.querySelector('#account-logout').addEventListener('click', () => logout());
    container.querySelector('#account-logout-all').addEventListener('click', () => logoutAll());

    const current = container.querySelector('#account-pw-current');
    const next = container.querySelector('#account-pw-new');
    const meter = container.querySelector('#account-pw-meter');
    const submit = container.querySelector('#account-pw-submit');
    const message = container.querySelector('#account-pw-message');
    function updatePw() {
      const strength = paintMeter(meter, next.value, policy);
      submit.disabled = !current.value || !strength || strength.level === 'red';
    }
    current.addEventListener('input', updatePw);
    next.addEventListener('input', updatePw);
    container.querySelector('#account-pw-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      submit.disabled = true;
      const result = await changePassword(current.value, next.value);
      message.hidden = false;
      message.classList.toggle('ok', result.ok);
      message.textContent = result.ok ? t('account.pw.changed') : errorText(result.code, result.retryAfter);
      if (result.ok) {
        current.value = '';
        next.value = '';
      }
      updatePw();
    });

    const list = container.querySelector('#account-invite-list');
    const newBox = container.querySelector('#account-invite-new');
    const inviteError = container.querySelector('#account-invite-error');
    async function loadInvitations() {
      const result = await listInvitations();
      if (!result.ok) return;
      list.innerHTML = result.data
        .map(
          (inv) => `<li><span class="account-invite-state" data-state="${escapeAttr(inv.state)}">${escapeHtml(t(`account.invitations.state.${inv.state}`))}</span>
            ${new Date(inv.expires_at * 1000).toLocaleString()}
            ${inv.state === 'open' ? `<button type="button" data-revoke="${escapeAttr(inv.id)}">${t('account.invitations.revoke')}</button>` : ''}</li>`,
        )
        .join('');
      list.querySelectorAll('[data-revoke]').forEach((btn) =>
        btn.addEventListener('click', async () => {
          await revokeInvitation(btn.dataset.revoke);
          loadInvitations();
        }),
      );
    }
    container.querySelector('#account-invite-create').addEventListener('click', async () => {
      inviteError.hidden = true;
      const result = await createInvitation();
      if (!result.ok) {
        inviteError.textContent = errorText(result.code, result.retryAfter);
        inviteError.hidden = false;
        return;
      }
      const link = `${window.location.origin}${window.location.pathname}#invite=${encodeURIComponent(result.data.token)}`;
      // The token is shown exactly once (only its digest is stored server-side).
      newBox.hidden = false;
      newBox.innerHTML = `<p class="hint">${t('account.invitations.shownOnce')}</p>
        <input type="text" readonly value="${escapeAttr(result.data.token)}" aria-label="${escapeAttr(t('account.invitations.token'))}" />
        <button type="button" id="account-copy-token">${t('account.invitations.copyToken')}</button>
        <button type="button" id="account-copy-link">${t('account.invitations.copyLink')}</button>`;
      newBox.querySelector('#account-copy-token').addEventListener('click', () => navigator.clipboard?.writeText(result.data.token));
      newBox.querySelector('#account-copy-link').addEventListener('click', () => navigator.clipboard?.writeText(link));
      loadInvitations();
    });
    loadInvitations();
  }

  function render(auth) {
    if (auth.authenticated) renderLoggedIn(auth);
    else renderLoggedOut();
  }

  subscribeAuth(render);
  render(getAuth());
}
