// Administration page (PLR-9d, plan section 6). Plain forms and tables.
//
// No cookie, no storage: the admin name and password live in this module's memory only, are
// sent as `Authorization: Basic` with every request, and are dropped on "Abmelden" or after
// IDLE_LIMIT_MS without use. Every string that came from the server (player names, deck names,
// audit fields) is put into the DOM with textContent, never as HTML.

const IDLE_LIMIT_MS = 5 * 60 * 1000;
const POLL_INTERVAL_MS = 2000;
const ADMIN_MIN_LENGTH_FALLBACK = 15;

const app = document.getElementById('app');
const messageBox = document.getElementById('message');
const banner = document.getElementById('banner');
const whoBox = document.getElementById('who');
const logoutButton = document.getElementById('logout');

/** @type {{name: string, password: string} | null} */
let credentials = null;
let idleTimer = null;
let pollTimer = null;
let serverState = { setup_open: false, admin_password_min_length: ADMIN_MIN_LENGTH_FALLBACK, run_mode: 'lan' };
/** Poll tokens of jobs started from this page, by job id (memory only). */
const pollTokens = new Map();

const ERRORS = {
  admin_auth_required: 'Name oder Passwort falsch.',
  admin_local_only: 'Die Administration ist nur auf dem Server-Rechner selbst erreichbar.',
  admin_disabled: 'Die Administration ist in diesem Betriebsmodus gesperrt (Fernzugriff braucht MFA).',
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
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(`/api/admin${path}`, init);
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
  if (serverState.run_mode === 'online') {
    app.replaceChildren(el('section', {}, el('p', { text: ERRORS.admin_disabled })));
    return;
  }
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
  const form = el('form', {
    onsubmit: async (event) => {
      event.preventDefault();
      const attempt = { name: name.value, password: password.value };
      const result = await api('GET', '/whoami', { auth: attempt });
      if (result.ok) {
        credentials = attempt;
        password.value = '';
        enter(result.data.name);
      } else if (result.code === 'setup_required') {
        credentials = null;
        renderSetup(attempt);
      } else {
        say(describe(result), 'error');
      }
    },
  },
  field('Admin-Name', name), field('Passwort', password),
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
        say('Admin-Konto angelegt. Du kannst dich jetzt anmelden.', 'ok');
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
  }, el('p', { class: 'muted', text: 'Den Wiederherstellungs-Zugang erzeugt der Server-Betreiber mit scripts/manage_accounts.py recover.' }),
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
  const load = async () => {
    const result = await api('GET', `/players?q=${encodeURIComponent(query.value)}`);
    if (!result.ok) return say(describe(result), 'error');
    const rows = result.data.players.map((player) => el('tr', {},
      el('td', { text: player.name }),
      el('td', { text: player.disabled ? 'gesperrt' : 'aktiv' }),
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
  body.append(el('section', {}, el('h2', { text: 'Spieler' }), query, list));
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
      ? act('Entsperren', () => api('POST', `/players/${player.player_uuid}/enable`))
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
      el('td', { text: deck.name }), el('td', { text: deck.author || '' }), el('td', { text: deck.created_at }),
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

async function deleteDeckDialog(deck) {
  const preview = await api('GET', `/decks/${deck.id}/delete-preview`);
  if (!preview.ok) return say(describe(preview), 'error');
  const typed = el('input', { type: 'text', autocomplete: 'off' });
  const pass = el('input', { type: 'password', autocomplete: 'current-password' });
  app.replaceChildren(el('section', {},
    el('h2', { text: `Globales Deck löschen: ${deck.name}` }),
    el('p', { text: `Das Deck (${preview.data.lines} Zeilen) wird für alle Spieler entfernt. Bereits kopierte private Decks bleiben bestehen.` }),
    field('Zur Bestätigung den Decknamen eintippen', typed), field('Dein Admin-Passwort', pass),
    el('p', {}, el('button', { type: 'button', class: 'danger', text: 'Endgültig löschen', onclick: async () => {
      if (!pass.value || pass.value !== credentials.password) return say('Passwort zur Bestätigung falsch.', 'error');
      const result = await api('POST', `/decks/${deck.id}/delete`, { body: { confirm_name: typed.value } });
      if (!result.ok) return say(describe(result), 'error');
      showTab('decks', 'Deck gelöscht.', 'ok');
    } }), ' ', el('button', { type: 'button', text: 'Abbrechen', onclick: () => showTab('decks') }))));
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
  const password = el('input', { type: 'password', autocomplete: 'new-password', required: true });
  body.append(el('section', {}, el('h2', { text: 'Passwort ändern' }),
    field('Neues Passwort', password), passwordMeter(password),
    el('p', { class: 'muted', text: 'Passwort-Wiederherstellung und Rollenänderungen macht nur der Server-Betreiber.' }),
    el('p', {}, el('button', { type: 'button', text: 'Passwort ändern', onclick: async () => {
      const next = password.value;
      const result = await api('POST', '/password-change', { body: { new_password: next } });
      if (!result.ok) return say(describe(result), 'error');
      credentials = { name: credentials.name, password: next };
      password.value = '';
      say('Passwort geändert.', 'ok');
    } }))));
}

start();
