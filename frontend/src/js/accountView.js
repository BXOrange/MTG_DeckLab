// Account panel inside "Profil" (PLR-9a): login, signup by invitation token, password
// change with the red/yellow/green meter, invitations and logout. Plan:
// docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md. All user/server text goes through escapeHtml/t().
//
// VIS-21: profileView.js shows the panel in three tabs, so `renderAccountPanel` takes the
// `section` to draw: 'login' (login/signup/recover; once logged in the account name, logout and
// deletion), 'sessions' (own sessions, logout-all, invitations) or 'password' (change). The
// latter two are only reachable while logged in (the Profil tabs are disabled otherwise).


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
  listSessions,
  revokeSession,
  fetchPasswordPolicy,
  recoverPassword,
  deleteAccount,
  FALLBACK_PLAYER_NAME,
} from './auth.js';
import { passwordStrength } from './passwordStrength.js';
import { escapeHtml } from './cardTile.js';
import { escapeAttr } from './gameSetup.js';
import { t } from './i18n.js';

/** The Profil account sections (one Profil tab each, VIS-21). */
export const ACCOUNT_SECTIONS = Object.freeze({ LOGIN: 'login', SESSIONS: 'sessions', PASSWORD: 'password' });

// Fallback until GET /api/auth/policy answers; the server value wins.
const DEFAULT_POLICY = { min_length: 10, green_length: 12, deletion_grace_days: 7 };

/** One-shot message for the logged-out view (set after a self-requested deletion ends the session). */
let loggedOutNotice = '';

/** Invitation token from a shared link (`#invite=...`): the fragment never reaches the server. */
function inviteFromHash() {
  const match = /(?:^|[#&])invite=([^&]+)/.exec(window.location.hash);
  return match ? decodeURIComponent(match[1]) : '';
}

const KNOWN_ERRORS = new Set([
  'unreachable', 'rate_limited', 'invalid_credentials', 'invalid_invitation', 'name_taken', 'invalid_name',
  'password_too_short', 'password_blocklisted', 'password_too_long', 'invitation_limit', 'csrf', 'unauthenticated',
  'invalid_recovery', 'protected_account',
]);

function errorText(code, retryAfter = 0, serverMessage = '') {
  // VIS-24: a code this view has no wording for shows the server's localized message.
  const message = KNOWN_ERRORS.has(code)
    ? t(`account.error.${code}`)
    : serverMessage || t('account.error.generic');
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

export function renderAccountPanel(container, { section = ACCOUNT_SECTIONS.LOGIN } = {}) {
  let policy = DEFAULT_POLICY;
  fetchPasswordPolicy().then((result) => {
    if (result.ok) policy = { ...DEFAULT_POLICY, ...result.data };
  });

  function renderLoggedOut() {
    const invite = inviteFromHash();
    const notice = loggedOutNotice;
    loggedOutNotice = '';
    container.innerHTML = `
      <div class="deck-section account-panel">
        <h3>${t('account.heading')}</h3>
        <p class="hint">${t('account.loggedOut')}</p>
        ${notice ? `<p class="account-error ok" role="status">${escapeHtml(notice)}</p>` : ''}
        <div class="account-tabs" role="tablist">
          <button type="button" class="account-tab ${invite ? '' : 'active'}" data-mode="login">${t('account.login')}</button>
          <button type="button" class="account-tab ${invite ? 'active' : ''}" data-mode="signup">${t('account.signup')}</button>
          <button type="button" class="account-tab" data-mode="recover">${t('account.recover.tab')}</button>
        </div>
        <form id="account-form" autocomplete="on" novalidate>
          <div class="mp-option-row"><label for="account-name">${t('account.name')}</label>
            <input id="account-name" name="username" type="text" autocomplete="username" maxlength="64" required /></div>
          <div class="mp-option-row" data-signup-only hidden><label for="account-invite">${t('account.invitation')}</label>
            <input id="account-invite" type="text" autocomplete="off" spellcheck="false" value="${escapeAttr(invite)}" /></div>
          <p class="hint" data-recover-only hidden>${t('account.recover.hint')}</p>
          <div class="mp-option-row" data-recover-only hidden><label for="account-recovery">${t('account.recover.token')}</label>
            <input id="account-recovery" type="text" autocomplete="off" spellcheck="false" maxlength="256" /></div>
          <div class="mp-option-row"><label for="account-password" id="account-password-label">${t('account.password')}</label>
            <input id="account-password" name="password" type="password" maxlength="1024" required /></div>
          <div data-meter-only hidden>${meterHtml('account-meter')}<p class="hint">${t('account.pw.hint', { min: policy.min_length })}</p></div>
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
    const recoverOnly = container.querySelectorAll('[data-recover-only]');
    const meterOnly = container.querySelectorAll('[data-meter-only]');
    const passwordLabel = container.querySelector('#account-password-label');
    let mode = invite ? 'signup' : 'login';

    function applyMode() {
      signupOnly.forEach((el) => {
        el.hidden = mode !== 'signup';
      });
      recoverOnly.forEach((el) => {
        el.hidden = mode !== 'recover';
      });
      meterOnly.forEach((el) => {
        el.hidden = mode === 'login';
      });
      container.querySelectorAll('.account-tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.mode === mode));
      submit.textContent = { signup: t('account.signup'), recover: t('account.recover.submit') }[mode] || t('account.login');
      passwordLabel.textContent = mode === 'recover' ? t('account.pw.new') : t('account.password');
      passwordInput.autocomplete = mode === 'login' ? 'current-password' : 'new-password';
      update();
    }
    function update() {
      const strength = paintMeter(meter, passwordInput.value, policy);
      // Red blocks submitting a new password; yellow does not (plan §3).
      submit.disabled = mode !== 'login' && (!strength || strength.level === 'red');
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
      if (mode === 'recover') {
        const recovered = await recoverPassword(name, container.querySelector('#account-recovery').value.trim(), password);
        error.classList.toggle('ok', recovered.ok);
        error.textContent = recovered.ok ? t('account.recover.done') : errorText(recovered.code, recovered.retryAfter, recovered.message);
        error.hidden = false;
        if (recovered.ok) {
          passwordInput.value = '';
          container.querySelector('#account-recovery').value = '';
          mode = 'login';
          applyMode();
        } else {
          update();
        }
        return;
      }
      error.classList.remove('ok');
      const result =
        mode === 'signup'
          ? await signup(name, password, container.querySelector('#account-invite').value.trim())
          : await login(name, password);
      if (!result.ok) {
        error.textContent = errorText(result.code, result.retryAfter, result.message);
        error.hidden = false;
        update();
        return;
      }
      if (mode === 'signup' && inviteFromHash()) history.replaceState(null, '', window.location.pathname + window.location.search);
    });
    applyMode();
  }

  function renderLoggedIn(auth) {
    const sections = {
      [ACCOUNT_SECTIONS.LOGIN]: `
        <h3>${t('account.heading')}</h3>
        <p>${t('account.signedInAs')} <strong>${escapeHtml(auth.name)}</strong></p>
        <div class="import-actions">
          <button type="button" id="account-logout">${t('account.logout')}</button>
        </div>

        <h4>${t('account.delete.heading')}</h4>
        <p class="hint">${t('account.delete.hint', { days: policy.deletion_grace_days })}</p>
        <div class="import-actions"><button type="button" id="account-delete-open">${t('account.delete.open')}</button></div>
        <form id="account-delete-form" autocomplete="off" novalidate hidden>
          <p class="hint">${t('account.delete.confirmName', { name: escapeHtml(auth.name) })}</p>
          <div class="mp-option-row"><label for="account-delete-name">${t('account.name')}</label>
            <input id="account-delete-name" type="text" autocomplete="off" maxlength="64" /></div>
          <div class="mp-option-row"><label for="account-delete-password">${t('account.password')}</label>
            <input id="account-delete-password" type="password" autocomplete="current-password" maxlength="1024" /></div>
          <div class="import-actions">
            <button type="submit" id="account-delete-submit" disabled>${t('account.delete.submit')}</button>
            <button type="button" id="account-delete-cancel">${t('account.delete.cancel')}</button>
          </div>
          <p class="account-error" id="account-delete-message" role="alert" hidden></p>
        </form>`,
      [ACCOUNT_SECTIONS.PASSWORD]: `
        <h4>${t('account.changePassword')}</h4>
        <form id="account-pw-form" autocomplete="off" novalidate>
          <div class="mp-option-row"><label for="account-pw-current">${t('account.pw.current')}</label>
            <input id="account-pw-current" type="password" autocomplete="current-password" maxlength="1024" /></div>
          <div class="mp-option-row"><label for="account-pw-new">${t('account.pw.new')}</label>
            <input id="account-pw-new" type="password" autocomplete="new-password" maxlength="1024" /></div>
          ${meterHtml('account-pw-meter')}
          <div class="import-actions"><button type="submit" id="account-pw-submit" disabled>${t('account.changePassword')}</button></div>
          <p class="account-error" id="account-pw-message" role="status" hidden></p>
        </form>`,
      [ACCOUNT_SECTIONS.SESSIONS]: `
        <div class="import-actions"><button type="button" id="account-logout-all">${t('account.logoutAll')}</button></div>
        <h4>${t('account.sessions.heading')}</h4>
        <ul id="account-session-list" class="account-invite-list"></ul>

        <h4>${t('account.invitations.heading')}</h4>
        <p class="hint">${t('account.invitations.hint')}</p>
        <div class="import-actions"><button type="button" id="account-invite-create">${t('account.invitations.create')}</button></div>
        <div id="account-invite-new" hidden></div>
        <ul id="account-invite-list" class="account-invite-list"></ul>
        <p class="account-error" id="account-invite-error" role="alert" hidden></p>`,
    };
    container.innerHTML = `
      <div class="deck-section account-panel">
${sections[section] || sections[ACCOUNT_SECTIONS.LOGIN]}
      </div>`;

    container.querySelector('#account-logout')?.addEventListener('click', () => logout());
    container.querySelector('#account-logout-all')?.addEventListener('click', () => logoutAll());

    if (section === ACCOUNT_SECTIONS.PASSWORD) {
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
        message.textContent = result.ok ? t('account.pw.changed') : errorText(result.code, result.retryAfter, result.message);
        if (result.ok) {
          current.value = '';
          next.value = '';
        }
        updatePw();
      });
    }

    if (section === ACCOUNT_SECTIONS.LOGIN) {
      const deleteForm = container.querySelector('#account-delete-form');
      const deleteName = container.querySelector('#account-delete-name');
      const deletePassword = container.querySelector('#account-delete-password');
      const deleteSubmit = container.querySelector('#account-delete-submit');
      const deleteMessage = container.querySelector('#account-delete-message');
      function updateDelete() {
        deleteSubmit.disabled = deleteName.value.trim() !== auth.name || !deletePassword.value;
      }
      deleteName.addEventListener('input', updateDelete);
      deletePassword.addEventListener('input', updateDelete);
      container.querySelector('#account-delete-open').addEventListener('click', () => {
        deleteForm.hidden = false;
        deleteName.focus();
      });
      container.querySelector('#account-delete-cancel').addEventListener('click', () => {
        deleteForm.hidden = true;
        deleteForm.reset();
        deleteMessage.hidden = true;
        updateDelete();
      });
      deleteForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        deleteSubmit.disabled = true;
        const result = await deleteAccount(deletePassword.value);
        if (!result.ok) {
          deleteMessage.textContent = errorText(result.code, result.retryAfter, result.message);
          deleteMessage.hidden = false;
          updateDelete();
          return;
        }
        // refreshAuth() already swapped the panel to the logged-out view; leave a note there.
        loggedOutNotice = t('account.delete.done', { days: result.data.grace_days });
        render(getAuth());
      });
    }

    if (section === ACCOUNT_SECTIONS.SESSIONS) {
      const sessionList = container.querySelector('#account-session-list');
      async function loadSessions() {
        const result = await listSessions();
        if (!result.ok) return;
        sessionList.innerHTML = result.data
          .map(
            (sess) => `<li>${escapeHtml(new Date(sess.last_seen * 1000).toLocaleString())}
              ${sess.current ? `<strong>${t('account.sessions.current')}</strong>` : `<button type="button" data-revoke-session="${escapeAttr(sess.id)}">${t('account.sessions.end')}</button>`}</li>`,
          )
          .join('');
        sessionList.querySelectorAll('[data-revoke-session]').forEach((btn) =>
          btn.addEventListener('click', async () => {
            await revokeSession(btn.dataset.revokeSession);
            loadSessions();
          }),
        );
      }
      loadSessions();

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
          inviteError.textContent = errorText(result.code, result.retryAfter, result.message);
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
  }

  /** The sessions/password sections need an account; the Profil tabs are disabled without one. */
  function renderNeedsLogin() {
    container.innerHTML = `<div class="deck-section account-panel"><p class="empty-state">${t('profile.tabs.loginHint', { fallback: FALLBACK_PLAYER_NAME })}</p></div>`;
  }

  function render(auth) {
    if (auth.authenticated) renderLoggedIn(auth);
    else if (section === ACCOUNT_SECTIONS.LOGIN) renderLoggedOut();
    else renderNeedsLogin();
  }

  subscribeAuth(render);
  render(getAuth());
}
