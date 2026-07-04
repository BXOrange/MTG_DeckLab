// Goldfisch-Modus: play the loaded deck against the real backend rules
// engine (mtg_analyzer/game/) via the /api/game session endpoints. Unlike
// the local, rule-less preview in boardView.js, every move here is
// validated server-side and the board shown is the server's authoritative
// GameState. Supports advancing the turn step by step, playing/tapping/
// casting/attacking from the server's legal_actions, and — the point of a
// goldfish — restarting and rewinding at any time (UC3).

import { getState } from './state.js';
import {
  startGoldfish,
  sendGameAction,
  rewindGame,
  restartGame,
  endGame,
} from './api.js';

/**
 * Create a persistent goldfish controller. Its session survives across
 * `mount()` calls (e.g. toggling board modes) so switching away and back
 * doesn't drop the running game.
 */
export function createGoldfishView() {
  let sessionId = null;
  let view = null; // last session view from the server
  let status = '';
  let statusKind = '';
  let busy = false;
  let root = null;

  function mount(el) {
    root = el;
    render();
  }

  function setStatus(text, kind = '') {
    status = text;
    statusKind = kind;
  }

  // --- Actions ------------------------------------------------------------

  function deckSectionsFromState() {
    const { deck } = getState();
    if (!deck) return null;
    const toText = (entries) => entries.map((c) => `${c.qty} ${c.name}`).join('\n');
    return {
      commanderText: toText(deck.commanders || []),
      mainboardText: toText(deck.mainDeck || []),
    };
  }

  async function start() {
    const sections = deckSectionsFromState();
    if (!sections) {
      setStatus('Kein Deck geladen – zuerst im "Deck-Import" ein Deck parsen.', 'warning');
      render();
      return;
    }
    await withBusy('Spiel wird gestartet …', async () => {
      const res = await startGoldfish({ ...sections, shuffle: true });
      if (res.ok) {
        applyView(res.data);
        const notFound = res.data.notFound || [];
        setStatus(
          notFound.length
            ? `Gestartet. Nicht auflösbar: ${notFound.join(', ')}`
            : 'Goldfisch-Spiel gestartet.',
          notFound.length ? 'warning' : 'ok'
        );
      } else if (res.status === 422) {
        const detail = res.data?.detail || {};
        setStatus(
          `Keine spielbaren Karten. Nicht gefunden: ${(detail.notFound || []).join(', ')}`,
          'warning'
        );
      } else if (res.status === 0) {
        setStatus('Server nicht erreichbar.', 'warning');
      } else {
        setStatus(`Start fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  async function act(action) {
    if (!sessionId) return;
    await withBusy('…', async () => {
      const res = await sendGameAction(sessionId, action);
      if (res.ok) {
        applyView(res.data);
        setStatus('', '');
      } else if (res.status === 400) {
        setStatus(`Aktion nicht erlaubt: ${res.data?.detail ?? ''}`, 'warning');
      } else if (res.status === 404) {
        setStatus('Spielsitzung abgelaufen – bitte neu starten.', 'warning');
        sessionId = null;
        view = null;
      } else {
        setStatus(`Fehler (${res.status}).`, 'warning');
      }
    });
  }

  async function rewind() {
    if (!sessionId) return;
    await withBusy('Zug wird zurückgenommen …', async () => {
      const res = await rewindGame(sessionId, 1);
      if (res.ok) {
        applyView(res.data);
        setStatus('Letzter Zug rückgängig gemacht.', 'ok');
      } else {
        setStatus(`Rückgängig fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  async function restart() {
    if (!sessionId) return;
    await withBusy('Spiel wird neu gestartet …', async () => {
      const res = await restartGame(sessionId);
      if (res.ok) {
        applyView(res.data);
        setStatus('Spiel neu gestartet.', 'ok');
      } else {
        setStatus(`Neustart fehlgeschlagen (${res.status}).`, 'warning');
      }
    });
  }

  async function quit() {
    const id = sessionId;
    sessionId = null;
    view = null;
    setStatus('', '');
    render();
    if (id) await endGame(id); // best-effort server cleanup
  }

  function applyView(data) {
    sessionId = data.session_id;
    view = data;
  }

  async function withBusy(pendingText, fn) {
    busy = true;
    setStatus(pendingText, 'pending');
    render();
    try {
      await fn();
    } finally {
      busy = false;
      render();
    }
  }

  // --- Rendering ----------------------------------------------------------

  function render() {
    if (!root) return;
    if (!view) {
      renderStartPanel();
    } else {
      renderGame();
    }
  }

  function renderStartPanel() {
    const hasDeck = !!getState().deck;
    root.innerHTML = `
      <div class="goldfish-start">
        <h3>Goldfisch-Modus</h3>
        <p class="hint">
          Teste dein geladenes Deck ohne Gegner gegen die echten Regeln:
          Schritt für Schritt durch den Zug, Länder spielen, Mana tappen,
          Sprüche wirken – jederzeit mit <strong>Zurücknehmen</strong> und
          <strong>Neu starten</strong>.
        </p>
        <button id="gf-start-btn" type="button" class="primary" ${hasDeck ? '' : 'disabled'}>
          Goldfisch-Spiel starten
        </button>
        ${hasDeck ? '' : '<p class="empty-state">Zuerst im „Deck-Import“ eine Deckliste parsen.</p>'}
        ${statusHtml()}
      </div>
    `;
    root.querySelector('#gf-start-btn')?.addEventListener('click', start);
  }

  function renderGame() {
    const s = view.state;
    const me = s.players[0];
    const actions = view.legal_actions || [];
    const gameOver = s.game_over;

    root.innerHTML = `
      <div class="goldfish">
        <div class="gf-topbar">
          <div class="gf-turninfo">
            <span class="gf-turn">Zug ${s.turn_number}</span>
            <span class="gf-step">${escapeHtml(labelPhase(s.current_phase))} · ${escapeHtml(labelStep(s.current_step))}</span>
          </div>
          ${manaPoolHtml(me.mana_pool)}
          ${lifeBox('Leben', me.life)}
        </div>

        ${gameOver ? `<p class="server-status warning">Spiel beendet${s.winner_id ? ` – Sieger: ${escapeHtml(s.winner_id)}` : ''}.</p>` : ''}
        ${statusHtml()}

        <div class="gf-controls">
          <button id="gf-advance" type="button" class="primary" ${busy || gameOver ? 'disabled' : ''}>Nächster Schritt →</button>
          <button id="gf-autoturn" type="button" ${busy || gameOver ? 'disabled' : ''}>Auto-Zug</button>
          <button id="gf-rewind" type="button" ${busy || !view.can_rewind ? 'disabled' : ''}>↶ Zurücknehmen</button>
          <button id="gf-restart" type="button" ${busy ? 'disabled' : ''}>⟲ Neu starten</button>
          <button id="gf-quit" type="button">Beenden</button>
        </div>

        <div class="gf-zone gf-stack">
          <h4>Stack (${s.stack.length})</h4>
          ${s.stack.length ? `<ul class="gf-stack-list">${s.stack.map((it) => `<li>${escapeHtml(it.description || it.kind)}</li>`).join('')}</ul>` : '<p class="empty-state">leer</p>'}
        </div>

        <div class="gf-zone gf-battlefield">
          <h4>Battlefield (${s.battlefield.length})</h4>
          ${objGrid(s.battlefield, 'Keine Permanents')}
        </div>

        <div class="gf-zone-row">
          <div class="gf-zone gf-command">
            <h4>Command Zone</h4>
            ${objGrid(me.command, '–')}
          </div>
          <div class="gf-zone gf-graveyard">
            <h4>Friedhof (${me.graveyard.length})</h4>
            ${objGrid(me.graveyard, 'leer')}
          </div>
          <div class="gf-zone gf-library">
            <h4>Bibliothek</h4>
            <p class="library-count">${me.library_count} Karten</p>
          </div>
        </div>

        <div class="gf-zone gf-hand">
          <h4>Hand (${me.hand.length})</h4>
          ${objGrid(me.hand, 'leer')}
        </div>

        <div class="gf-zone gf-actions">
          <h4>Mögliche Aktionen</h4>
          ${actionsHtml(actions, gameOver)}
        </div>

        ${moveLogHtml(view.move_log)}
      </div>
    `;

    wire();
  }

  function wire() {
    root.querySelector('#gf-advance')?.addEventListener('click', () => act({ type: 'advance_step' }));
    root.querySelector('#gf-autoturn')?.addEventListener('click', () => act({ type: 'auto_turn' }));
    root.querySelector('#gf-rewind')?.addEventListener('click', rewind);
    root.querySelector('#gf-restart')?.addEventListener('click', restart);
    root.querySelector('#gf-quit')?.addEventListener('click', quit);

    root.querySelectorAll('[data-action]').forEach((el) => {
      el.addEventListener('click', () => {
        act(JSON.parse(el.dataset.action));
      });
    });
  }

  // --- Rendering helpers --------------------------------------------------

  function actionsHtml(actions, gameOver) {
    if (gameOver) return '<p class="empty-state">Spiel beendet.</p>';
    const buttons = [];

    // Aggregate the per-creature "attack" actions into one declaration.
    const attackers = actions.filter((a) => a.type === 'attack').map((a) => a.instance_id);
    if (attackers.length) {
      const action = JSON.stringify({ type: 'declare_attackers', instance_ids: attackers });
      buttons.push(`<button type="button" data-action='${escapeAttr(action)}'>⚔️ Angreifen (${attackers.length})</button>`);
    }

    const labels = { play_land: '🌳 Land', cast_spell: '✨ Zaubern', tap_for_mana: '⟳ Tappen' };
    for (const a of actions) {
      if (!(a.type in labels)) continue;
      const action = JSON.stringify({ type: a.type, instance_id: a.instance_id, name: a.name });
      buttons.push(
        `<button type="button" data-action='${escapeAttr(action)}'>${labels[a.type]}: ${escapeHtml(a.name || '')}</button>`
      );
    }

    if (actions.some((a) => a.type === 'pass_priority') && view.state.stack.length) {
      const action = JSON.stringify({ type: 'pass_priority' });
      buttons.push(`<button type="button" data-action='${escapeAttr(action)}'>Stack auflösen</button>`);
    }

    return buttons.length
      ? `<div class="gf-action-buttons">${buttons.join('')}</div>`
      : '<p class="empty-state">Keine – „Nächster Schritt“ bringt den Zug voran.</p>';
  }

  function objGrid(objs, empty) {
    if (!objs.length) return `<p class="empty-state">${empty}</p>`;
    const imageCache = getState().imageCache;
    return `<div class="card-grid">${objs.map((o) => objCard(o, imageCache)).join('')}</div>`;
  }

  function objCard(o, imageCache) {
    const image = imageCache?.get((o.name || '').toLowerCase());
    const inner = image?.small
      ? `<img src="${image.small}" alt="${escapeHtml(o.name)}" loading="lazy" />`
      : escapeHtml(o.name);
    const classes = ['card'];
    if (image?.small) classes.push('has-image');
    if (o.tapped) classes.push('tapped');
    if (o.summoning_sick) classes.push('summoning-sick');
    const pt = o.power != null && o.toughness != null ? ` (${o.power}/${o.toughness})` : '';
    return `<div class="${classes.join(' ')}" data-hover-card="${escapeHtml(o.name)}" title="${escapeHtml(o.name)}${pt}${o.tapped ? ' — getappt' : ''}">${inner}</div>`;
  }

  function manaPoolHtml(pool) {
    const order = ['W', 'U', 'B', 'R', 'G', 'C'];
    const glyph = { W: '⚪', U: '🔵', B: '⚫', R: '🔴', G: '🟢', C: '⟡' };
    const parts = order.filter((c) => pool[c] > 0).map((c) => `<span class="gf-mana">${glyph[c]}${pool[c]}</span>`);
    return `<div class="gf-manapool" title="Mana-Pool">${parts.length ? parts.join('') : '<span class="empty-state">kein Mana</span>'}</div>`;
  }

  function moveLogHtml(log) {
    if (!log || !log.length) return '';
    const recent = log.slice(-8);
    return `<div class="gf-movelog"><h4>Verlauf</h4><ol>${recent.map((m) => `<li>${escapeHtml(m)}</li>`).join('')}</ol></div>`;
  }

  function statusHtml() {
    if (!status) return '';
    return `<p class="server-status ${statusKind}">${escapeHtml(status)}</p>`;
  }

  return { mount };
}

const PHASE_LABELS = {
  beginning: 'Anfang',
  precombat_main: 'Hauptphase I',
  combat: 'Kampf',
  postcombat_main: 'Hauptphase II',
  ending: 'Endphase',
};
const STEP_LABELS = {
  untap: 'Enttappen',
  upkeep: 'Versorgung',
  draw: 'Ziehen',
  main1: 'Hauptphase I',
  begin_combat: 'Kampfbeginn',
  declare_attackers: 'Angreifer',
  declare_blockers: 'Blocker',
  combat_damage: 'Kampfschaden',
  end_combat: 'Kampfende',
  main2: 'Hauptphase II',
  end: 'Ende',
  cleanup: 'Aufräumen',
};

function labelPhase(name) {
  return PHASE_LABELS[name] || name || '—';
}
function labelStep(name) {
  return STEP_LABELS[name] || name || '—';
}

function lifeBox(label, life) {
  return `<div class="gf-life"><span class="gf-life-label">${escapeHtml(label)}</span><span class="life-total">${life}</span></div>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}
