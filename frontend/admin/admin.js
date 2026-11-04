// Administration page (PLR-9d, plan section 6). Plain forms and tables.
//
// No cookie, no storage: the admin name and password live in this module's memory only, are
// sent as `Authorization: Basic` with every request, and are dropped on "Abmelden" or after
// IDLE_LIMIT_MS without use. With an authenticator (MFA) the page trades one verified code for a
// short-lived server-held grant (header `X-Admin-Grant`, memory only) so it need not ask for a
// fresh code on every request; the password still travels with each one. Every string that came from the server (player names, deck names,
// audit fields) is put into the DOM with textContent, never as HTML.

const IDLE_LIMIT_MS = 5 * 60 * 1000;
const POLL_INTERVAL_MS = 2000;
const ADMIN_MIN_LENGTH_FALLBACK = 15;

const app = document.getElementById('app');
const messageBox = document.getElementById('message');
const banner = document.getElementById('banner');
const whoBox = document.getElementById('who');
const logoutButton = document.getElementById('logout');

/** @type {{name: string, password: string, grant?: string} | null} */
let credentials = null;
let idleTimer = null;
let pollTimer = null;
let serverState = { setup_open: false, admin_password_min_length: ADMIN_MIN_LENGTH_FALLBACK, run_mode: 'lan' };
/** Poll tokens of jobs started from this page, by job id (memory only). */
const pollTokens = new Map();

const ERRORS = {
  admin_auth_required: 'Name oder Passwort falsch.',
  admin_local_only: 'Die Administration ist nur auf dem Server-Rechner selbst erreichbar.',
  admin_https_required: 'Fernzugriff auf die Administration geht nur über HTTPS.',
  admin_otp_required: 'Bitte den Code der Authenticator-App (oder einen Recovery-Code) eingeben.',
  mfa_enrollment_required: 'Dieses Konto ist erst nach der Einrichtung der Authenticator-App aktiv.',
  invalid_code: 'Der Code ist ungültig oder wurde schon verwendet.',
  current_code_required: 'Dafür wird ein aktueller Code oder ein Recovery-Code gebraucht.',
  otp_required: 'Für ein Token ist ein frisch eingegebener Code nötig.',
  mfa_required: 'In diesem Betriebsmodus ist die Authenticator-App Pflicht.',
  mfa_not_enrolled: 'Es ist keine Authenticator-App eingerichtet.',
  http_503: 'Das Token konnte nicht gespeichert werden.',
  setup_required: 'Die Ersteinrichtung ist noch nicht abgeschlossen.',
  setup_not_open: 'Die Ersteinrichtung ist bereits abgeschlossen.',
  rate_limited: 'Zu viele Fehlversuche. Bitte später erneut versuchen.',
  password_too_short: 'Das Passwort ist zu kurz.',
  password_too_long: 'Das Passwort ist zu lang.',
  password_blocklisted: 'Dieses Passwort ist zu verbreitet oder zu einfach.',
  password_reused_initial: 'Das Anfangspasswort darf nicht wieder verwendet werden.',
  invalid_invitation: 'Einladung ungültig, abgelaufen oder bereits benutzt.',
  invalid_recovery: 'Wiederherstellungs-Zugang ungültig oder abgelaufen.',
  name_taken: 'Der Name ist vergeben.',
  invalid_name: 'Der Name ist ungültig.',
  confirmation_mismatch: 'Die Bestätigung stimmt nicht überein.',
  protected_account: 'Dieses Konto ist geschützt.',
  not_found: 'Nicht gefunden.',
  job_running: 'Dieses Update läuft bereits.',
  unknown_job_kind: 'Unbekannte Update-Art.',
};

// -- DOM helpers (text only) ---------------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else if (value !== false && value != null) node.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  return node;
}

function say(text, kind = '') {
  messageBox.textContent = text;
  messageBox.className = kind;
}

function describe(error) {
  return ERRORS[error.code] || `Fehler (${error.code || error.status || 'unbekannt'}).`;
}

function when(epochSeconds) {
  return epochSeconds ? new Date(epochSeconds * 1000).toLocaleString('de-DE') : '';
}

function field(label, input) {
  return el('div', {}, el('label', { text: label }), input);
}

async function copyToClipboard(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = 'Kopiert';
  } catch {
    button.textContent = 'Kopieren nicht möglich';
  }
}

// -- API ------------------------------------------------------------------------------------

function basicHeader(name, password) {
  const bytes = new TextEncoder().encode(`${name}:${password}`);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return `Basic ${btoa(binary)}`;
}

/**
 * @returns {Promise<{ok: true, data: any} | {ok: false, code: string, status: number}>}
 */
async function api(method, path, { body, auth = credentials, headers = {} } = {}) {
  const init = { method, credentials: 'omit', cache: 'no-store', headers: { ...headers } };
  if (auth) init.headers.Authorization = basicHeader(auth.name, auth.password);
  if (auth && auth.grant) init.headers['X-Admin-Grant'] = auth.grant;
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path.startsWith('/api/') ? path : `/api/admin${path}`, init);
  } catch {
    return { ok: false, code: 'unreachable', status: 0 };
  }
  let data = null;
  if (response.status !== 204) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    const detail = data && data.detail;
    const code = (detail && detail.code) || `http_${response.status}`;
    if (response.status === 401 && auth === credentials) signOut('Anmeldung abgelaufen oder falsch.');
    return { ok: false, code, status: response.status };
  }
  touch();
  return { ok: true, data };
}

function touch() {
  clearTimeout(idleTimer);
  if (credentials) idleTimer = setTimeout(() => signOut('Wegen Inaktivität abgemeldet.'), IDLE_LIMIT_MS);
}

function signOut(text = '') {
  credentials = null;
  clearTimeout(idleTimer);
  clearTimeout(pollTimer);
  pollTokens.clear();
  logoutButton.hidden = true;
  whoBox.textContent = '';
  start().then(() => say(text));
}

logoutButton.addEventListener('click', () => signOut('Abgemeldet.'));

// -- start / login --------------------------------------------------------------------------

async function start() {
  const state = await api('GET', '/state', { auth: null });
  if (!state.ok) {
    app.replaceChildren(el('section', {}, el('p', { text: ERRORS[state.code] || 'Der Server ist nicht erreichbar.' })));
    banner.hidden = true;
    return;
  }
  serverState = state.data;
  banner.hidden = !serverState.setup_open;
  banner.textContent = serverState.setup_open
    ? 'Ersteinrichtung offen: Das Konto "admin" hat noch das Anfangspasswort. Bitte jetzt ein neues Passwort setzen.'
    : '';
  renderLogin();
}

function passwordMeter(input) {
  const out = el('p', { class: 'muted' });
  const update = () => {
    const need = serverState.admin_password_min_length;
    const have = [...input.value].length;
    out.textContent = have >= need ? `Länge ausreichend (${have} Zeichen).` : `Rot: ${have} von mindestens ${need} Zeichen.`;
  };
  input.addEventListener('input', update);
  update();
  return out;
}

function renderLogin() {
  const name = el('input', { type: 'text', autocomplete: 'username', required: true, value: serverState.setup_open ? 'admin' : '' });
  const password = el('input', { type: 'password', autocomplete: 'current-password', required: true });
  const otp = el('input', { type: 'text', autocomplete: 'one-time-code', inputmode: 'numeric', maxlength: 64, spellcheck: 'false' });
  const form = el('form', {
    onsubmit: async (event) => {
      event.preventDefault();
      const attempt = { name: name.value, password: password.value };
      const code = otp.value.trim();
      if (code) {
        // One verified code becomes a short-lived grant for this page (see the header comment).
        const granted = await api('POST', '/mfa/grant', { auth: attempt, headers: { 'X-Admin-OTP': code } });
        if (granted.ok) attempt.grant = granted.data.grant;
        else if (granted.code !== 'mfa_enrollment_required' && granted.code !== 'otp_required' && granted.code !== 'setup_required') {
          return say(describe(granted), 'error');
        }
      }
      const result = await api('GET', '/whoami', { auth: attempt });
      otp.value = '';
      if (result.ok) {
        credentials = attempt;
        password.value = '';
        enter(result.data.name);
      } else if (result.code === 'setup_required') {
        credentials = null;
        renderSetup(attempt);
      } else if (result.code === 'mfa_enrollment_required') {
        credentials = attempt;
        touch();
        renderEnrollment(attempt, { forced: true });
      } else {
        say(describe(result), 'error');
        if (result.code === 'admin_otp_required') otp.focus();
      }
    },
  },
  field('Admin-Name', name), field('Passwort', password),
  // PLR-19: a local connection needs name + password only, so the page does not ask for a code there.
  serverState.second_factor_required ? field('Authenticator-Code oder Recovery-Code (sobald eingerichtet; in --online immer)', otp) : null,
  el('p', {}, el('button', { type: 'submit', text: 'Anmelden' })),
  serverState.setup_open ? el('p', { class: 'muted', text: 'Erstanmeldung: Name "admin", Anfangspasswort laut Server-Anleitung.' }) : null);

  app.replaceChildren(
    el('section', {}, el('h2', { text: 'Anmelden' }), form),
    registerSection(),
    recoverSection(),
  );
}

function registerSection() {
  const name = el('input', { type: 'text', autocomplete: 'username', required: true });
  const password = el('input', { type: 'password', autocomplete: 'new-password', required: true });
  const invitation = el('input', { type: 'text', autocomplete: 'off', required: true });
  const form = el('form', {
    onsubmit: async (event) => {
      event.preventDefault();
      const result = await api('POST', '/signup', {
        auth: null, body: { name: name.value, password: password.value, invitation: invitation.value },
      });
      if (result.ok) {
        say(result.data.mfa_enrollment_required
          ? 'Admin-Konto angelegt. Melde dich an und richte die Authenticator-App ein; erst dann ist das Konto aktiv.'
          : result.data.mfa_enrollment_required_for_remote
            ? 'Admin-Konto angelegt. Lokal kannst du dich jetzt anmelden; für den Zugriff von außen richtest du vorher die Authenticator-App ein.'
            : 'Admin-Konto angelegt. Du kannst dich jetzt anmelden.', 'ok');
        form.reset();
      } else {
        say(describe(result), 'error');
      }
    },
  }, field('Admin-Einladung', invitation), field('Name', name), field('Passwort', password), passwordMeter(password),
  el('p', {}, el('button', { type: 'submit', text: 'Admin-Konto anlegen' })));
  return el('section', {}, el('h2', { text: 'Admin-Registrierung (mit Admin-Einladung)' }), form);
}

function recoverSection() {
  const name = el('input', { type: 'text', required: true });
  const token = el('input', { type: 'text', autocomplete: 'off', required: true });
  const password = el('input', { type: 'password', autocomplete: 'new-password', required: true });
  const form = el('form', {
    onsubmit: async (event) => {
      event.preventDefault();
      const result = await api('POST', '/recover', {
        auth: null, body: { name: name.value, recovery_token: token.value, new_password: password.value },
      });
      if (result.ok) {
        say('Passwort ersetzt. Bitte neu anmelden.', 'ok');
        form.reset();
      } else {
        say(describe(result), 'error');
      }
    },
  }, el('p', { class: 'muted', text: 'Den Wiederherstellungs-Zugang erzeugt der Server-Betreiber mit scripts/manage_accounts.py recover (für das allererste Admin-Konto in --online: create-admin NAME).' }),
  field('Admin-Name', name), field('Wiederherstellungs-Zugang', token), field('Neues Passwort', password), passwordMeter(password),
  el('p', {}, el('button', { type: 'submit', text: 'Passwort ersetzen' })));
  return el('section', {}, el('h2', { text: 'Passwort wiederherstellen' }), form);
}

// -- setup ----------------------------------------------------------------------------------

function renderSetup(initial) {
  const password = el('input', { type: 'password', autocomplete: 'new-password', required: true });
  const repeat = el('input', { type: 'password', autocomplete: 'new-password', required: true });
  const form = el('form', {
    onsubmit: async (event) => {
      event.preventDefault();
      if (password.value !== repeat.value) {
        say('Die beiden Passwörter sind verschieden.', 'error');
        return;
      }
      const result = await api('POST', '/setup', { auth: initial, body: { new_password: password.value } });
      if (!result.ok) {
        say(describe(result), 'error');
        return;
      }
      say('Ersteinrichtung abgeschlossen. Die Einladungen werden nur jetzt angezeigt.', 'ok');
      renderSetupDone(result.data);
    },
  }, el('p', { text: 'Schritt 1: Neues Admin-Passwort setzen.' }),
  field('Neues Passwort', password), passwordMeter(password), field('Wiederholen', repeat),
  el('p', {}, el('button', { type: 'submit', text: 'Passwort setzen und Einladungen erzeugen' })));
  app.replaceChildren(el('section', {}, el('h2', { text: 'Ersteinrichtung' }), form));
}

function tokenBox(label, token) {
  const copy = el('button', { type: 'button', text: 'Kopieren' });
  copy.addEventListener('click', () => copyToClipboard(token, copy));
  return el('div', {}, el('p', { text: label }), el('div', { class: 'token', text: token }), copy);
}

function renderSetupDone(data) {
  banner.hidden = true;
  app.replaceChildren(el('section', {},
    el('h2', { text: 'Einladungen' }),
    el('p', { text: 'Schritt 2: Gib die Tokens auf einem sicheren Weg weiter. Sie werden nicht noch einmal angezeigt.' }),
    tokenBox('Admin-Einladung (für die Admin-Registrierung auf dieser Seite)', data.invitations.admin),
    tokenBox('Spieler-Einladung (für die Anmeldung in der App)', data.invitations.player),
    el('p', {}, el('button', { type: 'button', text: 'Weiter zur Anmeldung', onclick: () => start() })),
  ));
}

// -- main -----------------------------------------------------------------------------------

const TABS = [
  ['players', 'Spieler', renderPlayers],
  ['invitations', 'Einladungen', renderInvitations],
  ['decks', 'Globale Decks', renderDecks],
  ['jobs', 'Datenbank-Updates', renderJobs],
  ['mcp', 'MCP-Token', renderMcp],
  ['audit', 'Audit-Log', renderAudit],
  ['account', 'Mein Konto', renderAccount],
];

function enter(name) {
  whoBox.textContent = `Angemeldet als ${name}`;
  logoutButton.hidden = false;
  banner.hidden = true;
  touch();
  showTab('players');
}

function showTab(id, text = '', kind = '') {
  clearTimeout(pollTimer);
  const nav = el('nav', {}, TABS.map(([key, label]) => el('button', {
    type: 'button', text: label, 'aria-current': key === id ? 'page' : null, onclick: () => showTab(key),
  })));
  const body = el('div');
  app.replaceChildren(nav, body);
  say(text, kind);
  TABS.find(([key]) => key === id)[2](body);
}

// -- players --------------------------------------------------------------------------------

async function renderPlayers(body) {
  const query = el('input', { type: 'search', placeholder: 'Name suchen' });
  const list = el('div');
  const pending = el('div');
  const loadPending = async () => {
    const result = await api('GET', '/pending-deletions');
    if (!result.ok) return;
    if (!result.data.pending.length) return pending.replaceChildren();
    const rows = result.data.pending.map((entry) => el('tr', {},
      el('td', { text: entry.name }),
      el('td', { text: when(entry.requested_at) }),
      el('td', { text: when(entry.due_at) }),
      el('td', {}, el('button', { type: 'button', text: 'Freigeben (Löschung abbrechen)', onclick: async () => {
        const done = await api('POST', `/players/${entry.player_uuid}/enable`);
        say(done.ok ? 'Konto freigegeben, die Löschung ist abgebrochen.' : describe(done), done.ok ? 'ok' : 'error');
        load();
      } }))));
    pending.replaceChildren(el('section', {},
      el('h2', { text: `Löschung angefordert (${result.data.pending.length})` }),
      el('p', { class: 'muted', text: `Spieler haben die Löschung ihres Kontos beantragt. Nach ${result.data.grace_days} Tagen wird das Konto endgültig gelöscht; bis dahin bricht „Freigeben“ die Löschung ab.` }),
      el('table', {}, el('thead', {}, el('tr', {}, ['Name', 'Beantragt', 'Fällig', ''].map((h) => el('th', { text: h })))), el('tbody', {}, rows))));
  };
  const load = async () => {
    loadPending();
    const result = await api('GET', `/players?q=${encodeURIComponent(query.value)}`);
    if (!result.ok) return say(describe(result), 'error');
    const rows = result.data.players.map((player) => el('tr', {},
      el('td', { text: player.name }),
      el('td', { text: player.deletion_due_at ? `Löschung fällig ${when(player.deletion_due_at)}` : (player.disabled ? 'gesperrt' : 'aktiv') }),
      el('td', { text: String(player.sessions) }),
      el('td', { text: when(player.created_at) }),
      el('td', {}, playerActions(player, load)),
    ));
    list.replaceChildren(
      el('p', { class: 'muted', text: `${result.data.total} Spieler` }),
      el('table', {}, el('thead', {}, el('tr', {}, ['Name', 'Status', 'Sitzungen', 'Angelegt', 'Aktionen'].map((h) => el('th', { text: h })))), el('tbody', {}, rows)),
    );
  };
  query.addEventListener('input', () => load());
  body.append(pending, el('section', {}, el('h2', { text: 'Spieler' }), query, list));
  load();
}

function playerActions(player, reload) {
  const act = (label, run, cls = '') => el('button', { type: 'button', text: label, class: cls, onclick: async () => {
    const result = await run();
    if (result && !result.ok) say(describe(result), 'error');
    else say('Erledigt.', 'ok');
    reload();
  } });
  const buttons = [];
  if (!player.is_default_local) {
    buttons.push(player.disabled
      ? act(player.deletion_due_at ? 'Freigeben (Löschung abbrechen)' : 'Entsperren', () => api('POST', `/players/${player.player_uuid}/enable`))
      : act('Sperren', () => api('POST', `/players/${player.player_uuid}/disable`)));
  }
  buttons.push(act('Sitzungen beenden', () => api('POST', `/players/${player.player_uuid}/revoke-sessions`)));
  if (!player.is_default_local) {
    buttons.push(el('button', { type: 'button', class: 'danger', text: 'Löschen …', onclick: () => deletePlayerDialog(player, reload) }));
  }
  return buttons;
}

async function deletePlayerDialog(player, reload) {
  const preview = await api('GET', `/players/${player.player_uuid}/delete-preview`);
  if (!preview.ok) return say(describe(preview), 'error');
  const typed = el('input', { type: 'text', autocomplete: 'off' });
  const pass = el('input', { type: 'password', autocomplete: 'current-password' });
  const go = el('button', { type: 'button', class: 'danger', text: 'Endgültig löschen', onclick: async () => {
    if (!pass.value || pass.value !== credentials.password) return say('Passwort zur Bestätigung falsch.', 'error');
    const result = await api('POST', `/players/${player.player_uuid}/delete`, { body: { confirm_name: typed.value } });
    if (!result.ok) return say(describe(result), 'error');
    showTab('players', `Konto gelöscht (${result.data.decks} Decks, ${result.data.assets} Dateien, ${result.data.sessions} Sitzungen).`, 'ok');
  } });
  const box = el('section', {},
    el('h2', { text: `Konto löschen: ${player.name}` }),
    el('p', { text: `Entfernt ${preview.data.decks} private Decks, ${preview.data.assets} hochgeladene Dateien und ${preview.data.sessions} Sitzungen. Der Name bleibt ${preview.data.tombstone_days} Tage gesperrt. Das lässt sich nicht rückgängig machen.` }),
    field('Zur Bestätigung den Namen eintippen', typed), field('Dein Admin-Passwort', pass),
    el('p', {}, go, ' ', el('button', { type: 'button', text: 'Abbrechen', onclick: () => showTab('players') })));
  app.replaceChildren(box);
}

// -- invitations ----------------------------------------------------------------------------

async function renderInvitations(body) {
  const list = el('div');
  const created = el('div');
  const load = async () => {
    const result = await api('GET', '/invitations');
    if (!result.ok) return say(describe(result), 'error');
    const rows = result.data.map((inv) => el('tr', {},
      el('td', { text: inv.id }), el('td', { text: inv.role }), el('td', { text: inv.state }),
      el('td', { text: when(inv.expires_at) }),
      el('td', {}, inv.state === 'open'
        ? el('button', { type: 'button', text: 'Widerrufen', onclick: async () => {
          const r = await api('DELETE', `/invitations/${inv.id}`);
          if (!r.ok) say(describe(r), 'error');
          load();
        } })
        : null),
    ));
    list.replaceChildren(el('table', {}, el('thead', {}, el('tr', {}, ['Kennung', 'Rolle', 'Zustand', 'Läuft ab', ''].map((h) => el('th', { text: h })))), el('tbody', {}, rows)));
  };
  const make = (role, label) => el('button', { type: 'button', text: label, onclick: async () => {
    const result = await api('POST', '/invitations', { body: { role } });
    if (!result.ok) return say(describe(result), 'error');
    created.replaceChildren(tokenBox(`Neue ${role === 'admin' ? 'Admin' : 'Spieler'}-Einladung (nur jetzt sichtbar)`, result.data.token));
    load();
  } });
  body.append(el('section', {}, el('h2', { text: 'Einladungen' }),
    el('p', {}, make('player', 'Spieler-Einladung erzeugen'), ' ', make('admin', 'Admin-Einladung erzeugen')), created, list));
  load();
}

// -- global decks ---------------------------------------------------------------------------

async function renderDecks(body) {
  const list = el('div');
  const editor = el('div');
  const load = async () => {
    const result = await api('GET', '/decks');
    if (!result.ok) return say(describe(result), 'error');
    const rows = result.data.map((deck) => el('tr', {},
      el('td', { text: deckLabel(deck.name) }), el('td', { text: deck.author || '' }), el('td', { text: deck.created_at }),
      el('td', {},
        el('button', { type: 'button', text: 'Bearbeiten', onclick: () => edit(deck.id) }), ' ',
        el('button', { type: 'button', class: 'danger', text: 'Löschen …', onclick: () => deleteDeckDialog(deck) })),
    ));
    list.replaceChildren(el('table', {}, el('thead', {}, el('tr', {}, ['Name', 'Autor', 'Angelegt', ''].map((h) => el('th', { text: h })))), el('tbody', {}, rows)));
  };
  const form = (deck) => {
    const name = el('input', { type: 'text', value: deck ? deck.name : '' });
    const author = el('input', { type: 'text', value: deck && deck.author ? deck.author : '' });
    const commander = el('textarea', { text: deck ? deck.commanderText : '' });
    const main = el('textarea', { text: deck ? deck.mainboardText : '' });
    const side = el('textarea', { text: deck ? deck.sideboardText : '' });
    const cube = el('input', { type: 'checkbox', checked: deck && deck.is_cube });
    cube.checked = Boolean(deck && deck.is_cube);
    editor.replaceChildren(el('section', {}, el('h2', { text: deck ? 'Globales Deck bearbeiten' : 'Neues globales Deck' }),
      field('Name', name), field('Autor', author), field('Commander', commander), field('Mainboard', main), field('Sideboard', side),
      el('label', {}, cube, ' Cube (keine Commander-Prüfung)'),
      el('p', {}, el('button', { type: 'button', text: 'Speichern', onclick: async () => {
        const payload = {
          name: name.value, author: author.value || null, commanderText: commander.value,
          mainboardText: main.value, sideboardText: side.value, isCube: cube.checked,
        };
        const result = deck ? await api('PUT', `/decks/${deck.id}`, { body: payload }) : await api('POST', '/decks', { body: payload });
        if (!result.ok) return say(describe(result), 'error');
        say('Gespeichert.', 'ok');
        editor.replaceChildren();
        load();
      } }), ' ', el('button', { type: 'button', text: 'Abbrechen', onclick: () => editor.replaceChildren() }))));
  };
  const edit = async (id) => {
    const result = await api('GET', `/decks/${id}`);
    if (!result.ok) return say(describe(result), 'error');
    form(result.data);
  };
  body.append(el('section', {}, el('h2', { text: 'Globale Decks' }),
    el('p', {}, el('button', { type: 'button', text: 'Neues Deck', onclick: () => form(null) })), editor, list));
  load();
}

const UNNAMED_DECK = 'Unbenanntes Deck';

function deckLabel(name) {
  return name && name.trim() ? name : UNNAMED_DECK;
}

function germanDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso || '') : date.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

// One plain yes/no question (VIS-22); window.confirm renders text only, so card/user text cannot inject HTML.
async function deleteDeckDialog(deck) {
  const preview = await api('GET', `/decks/${deck.id}/delete-preview`);
  if (!preview.ok) return say(describe(preview), 'error');
  const info = preview.data;
  const who = info.author && info.author.trim() ? info.author : `unbekannt (angelegt am ${germanDate(info.created_at)})`;
  if (!window.confirm(`Sind Sie sicher, dass Sie das Deck „${deckLabel(info.name)}“ von ${who} löschen wollen?`)) return;
  const result = await api('POST', `/decks/${deck.id}/delete`);
  if (!result.ok) return say(describe(result), 'error');
  showTab('decks', 'Deck gelöscht.', 'ok');
}

// -- update jobs ----------------------------------------------------------------------------

const JOB_LABELS = { 'card-pool': 'Karten-Datenbank (Scryfall)', combos: 'Combo-Datenbank (Commander Spellbook)' };

async function renderJobs(body) {
  const list = el('div');
  const render = (jobs) => {
    list.replaceChildren(...jobs.map((job) => el('section', {},
      el('h2', { text: `${JOB_LABELS[job.kind] || job.kind}: ${job.state}` }),
      el('p', { class: 'muted', text: `gestartet ${when(job.started_at)}${job.finished_at ? `, beendet ${when(job.finished_at)}` : ''}` }),
      job.error ? el('p', { text: `Fehler: ${job.error}` }) : null,
      el('pre', { text: job.progress.join('\n') || '(noch keine Ausgabe)' }))));
  };
  const poll = async () => {
    const result = await api('GET', '/jobs');
    if (!result.ok) return say(describe(result), 'error');
    const jobs = [];
    for (const job of result.data.jobs) {
      const token = pollTokens.get(job.id);
      // A job started here is followed with its own poll token, without sending the password.
      const view = token ? await api('GET', `/jobs/${job.id}`, { auth: null, headers: { 'X-Job-Token': token } }) : null;
      jobs.push(view && view.ok ? view.data : job);
    }
    render(jobs);
    if (jobs.some((job) => job.state === 'running')) pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
  };
  const startButtons = ['card-pool', 'combos'].map((kind) => el('button', { type: 'button', text: `${JOB_LABELS[kind]} aktualisieren`, onclick: async () => {
    const result = await api('POST', '/jobs', { body: { kind } });
    if (!result.ok) return say(describe(result), 'error');
    pollTokens.set(result.data.job.id, result.data.poll_token);
    say('Update gestartet.', 'ok');
    clearTimeout(pollTimer);
    poll();
  } }));
  body.append(el('section', {}, el('h2', { text: 'Datenbank-Updates' }), el('p', {}, startButtons[0], ' ', startButtons[1])), list);
  poll();
}

// -- MCP token (PLR-17) ---------------------------------------------------------------------

function renderMcp(body) {
  const shown = el('div');
  body.append(el('section', {}, el('h2', { text: 'MCP-Server-Token' }),
    el('p', { text: 'Spieler sehen das Token (und die Einrichtungsbefehle) unter Einstellungen; erzeugen oder erneuern kann es nur ein Administrator. Ein neues Token trennt bestehende MCP-Verbindungen.' }),
    el('p', {}, el('button', { type: 'button', class: 'danger', text: 'Token erzeugen / erneuern', onclick: async () => {
      if (!window.confirm('Ein neues Token trennt bestehende MCP-Verbindungen. Fortfahren?')) return;
      const result = await api('POST', '/api/mcp-settings/rotate');
      if (!result.ok) return say(describe(result), 'error');
      say('Neues Token erzeugt.', 'ok');
      shown.replaceChildren(tokenBox('Neues Server-Token (die Spieler-Oberfläche zeigt es ebenfalls)', result.data.server_token));
    } })), shown));
}

// -- MFA (authenticator app) -----------------------------------------------------------------

/**
 * Enrolment or replacement. `auth` is the credential object used for the calls; `forced` is the
 * `--online` case where nothing else works yet. `current` is the code that authorises a replacement.
 */
async function renderEnrollment(auth, { forced = false, current = null, then = null } = {}) {
  const started = await api('POST', '/mfa/enroll', { auth, body: current ? { current } : {} });
  if (!started.ok) {
    say(describe(started), 'error');
    if (!forced && then) then();
    return;
  }
  const code = el('input', { type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: 12, required: true });
  const form = el('form', {
    onsubmit: async (event) => {
      event.preventDefault();
      const confirmed = await api('POST', '/mfa/confirm', { auth, body: { code: code.value.trim() } });
      if (!confirmed.ok) return say(describe(confirmed), 'error');
      credentials = { name: auth.name, password: auth.password, grant: confirmed.data.grant };
      touch();
      renderRecoveryCodes(confirmed.data.recovery_codes, () => enter(auth.name));
    },
  },
  el('p', { text: `Schritt 2: Den ${started.data.digits}-stelligen Code der App eingeben, um die Einrichtung zu bestätigen.` }),
  field('Code aus der App', code),
  el('p', {}, el('button', { type: 'submit', text: 'Bestätigen' }),
    forced ? null : [' ', el('button', { type: 'button', text: 'Abbrechen', onclick: () => (then ? then() : showTab('account')) })]));
  app.replaceChildren(el('section', {},
    el('h2', { text: forced ? 'Authenticator-App einrichten (Pflicht)' : 'Authenticator-App einrichten' }),
    forced ? el('p', { text: 'In diesem Betriebsmodus ist das Konto erst nach der Einrichtung aktiv.' }) : null,
    el('p', { text: `Schritt 1: Trage den geheimen Schlüssel in einer Authenticator-App ein (TOTP, ${started.data.digits} Stellen, ${started.data.period_seconds} Sekunden). Ein QR-Code wird absichtlich nicht angezeigt; die Seite lädt nichts Externes.` }),
    tokenBox('Geheimer Schlüssel (Base32)', started.data.secret),
    tokenBox('Oder als otpauth-Adresse (zum Einfügen)', started.data.otpauth_uri),
    form));
}

function renderRecoveryCodes(codes, next) {
  const text = codes.join('\n');
  const copy = el('button', { type: 'button', text: 'Alle kopieren' });
  copy.addEventListener('click', () => copyToClipboard(text, copy));
  app.replaceChildren(el('section', {},
    el('h2', { text: 'Recovery-Codes' }),
    el('p', { text: 'Bewahre diese Codes sicher auf (z. B. Passwort-Manager, ausgedruckt). Jeder gilt einmal und ersetzt den App-Code, falls das Gerät verloren geht. Sie werden nicht noch einmal angezeigt.' }),
    el('pre', { class: 'token', text }), copy,
    el('p', {}, el('button', { type: 'button', text: 'Ich habe sie gesichert – weiter', onclick: next }))));
  say('Authenticator-App eingerichtet.', 'ok');
}

async function renderMfaSection(body) {
  const status = await api('GET', '/mfa');
  if (!status.ok) return;
  const current = el('input', { type: 'text', autocomplete: 'off', placeholder: 'App-Code oder Recovery-Code' });
  const buttons = [];
  const needCode = (run) => () => {
    if (!current.value.trim()) return say(ERRORS.current_code_required, 'error');
    run(current.value.trim());
  };
  if (!status.data.enrolled) {
    buttons.push(el('button', { type: 'button', text: 'Authenticator-App einrichten', onclick: () => renderEnrollment(credentials, { then: () => showTab('account') }) }));
  } else {
    buttons.push(
      el('button', { type: 'button', text: 'Authenticator-App ersetzen', onclick: needCode((code) => renderEnrollment(credentials, { current: code, then: () => showTab('account') })) }), ' ',
      el('button', { type: 'button', text: 'Neue Recovery-Codes', onclick: needCode(async (code) => {
        const result = await api('POST', '/mfa/recovery-codes', { body: { current: code } });
        if (!result.ok) return say(describe(result), 'error');
        credentials = { ...credentials, grant: result.data.grant };
        renderRecoveryCodes(result.data.recovery_codes, () => showTab('account'));
      }) }));
    if (!status.data.required) {
      buttons.push(' ', el('button', { type: 'button', class: 'danger', text: 'Authenticator-App ausschalten', onclick: needCode(async (code) => {
        const result = await api('POST', '/mfa/disable', { body: { current: code } });
        if (!result.ok) return say(describe(result), 'error');
        credentials = { name: credentials.name, password: credentials.password };
        showTab('account', 'Authenticator-App ausgeschaltet.', 'ok');
      }) }));
    }
  }
  body.append(el('section', {}, el('h2', { text: 'Authenticator-App (MFA)' }),
    el('p', { text: status.data.enrolled
      ? `Eingerichtet. Übrige Recovery-Codes: ${status.data.recovery_codes_left}.${status.data.required ? ' In diesem Betriebsmodus ist MFA Pflicht.' : ''}`
      : (status.data.required ? 'Pflicht in diesem Betriebsmodus.' : 'Optional auf dem Server-Rechner; empfohlen. Sobald eingerichtet, wird der Code bei jeder Anmeldung verlangt.') }),
    status.data.enrolled ? field('Aktueller Code (für Ersetzen, neue Recovery-Codes, Ausschalten)', current) : null,
    el('p', {}, buttons)));
}

// -- audit ----------------------------------------------------------------------------------

async function renderAudit(body) {
  const result = await api('GET', '/audit');
  if (!result.ok) return say(describe(result), 'error');
  const rows = result.data.entries.map((entry) => el('tr', {},
    el('td', { text: when(entry.at) }), el('td', { text: entry.actor }), el('td', { text: entry.action }),
    el('td', { text: entry.target }), el('td', { text: entry.result })));
  body.append(el('section', {}, el('h2', { text: `Audit-Log (${result.data.total} Einträge)` }),
    el('table', {}, el('thead', {}, el('tr', {}, ['Zeit', 'Akteur', 'Aktion', 'Ziel', 'Ergebnis'].map((h) => el('th', { text: h })))), el('tbody', {}, rows))));
}

// -- own account ----------------------------------------------------------------------------

function renderAccount(body) {
  renderMfaSection(body);
  const password = el('input', { type: 'password', autocomplete: 'new-password', required: true });
  body.append(el('section', {}, el('h2', { text: 'Passwort ändern' }),
    field('Neues Passwort', password), passwordMeter(password),
    el('p', { class: 'muted', text: 'Passwort-Wiederherstellung und Rollenänderungen macht nur der Server-Betreiber.' }),
    el('p', {}, el('button', { type: 'button', text: 'Passwort ändern', onclick: async () => {
      const next = password.value;
      const result = await api('POST', '/password-change', { body: { new_password: next } });
      if (!result.ok) return say(describe(result), 'error');
      password.value = '';
      if (credentials.grant) return signOut('Passwort geändert. Bitte neu anmelden (die Freigabe war an das alte Passwort gebunden).');
      credentials = { name: credentials.name, password: next };
      say('Passwort geändert.', 'ok');
    } }))));
}

start();
