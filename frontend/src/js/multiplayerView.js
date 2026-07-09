// "Multiplayer" tab: a stub. The backend already exposes
// POST /api/game/multiplayer (mtg_analyzer/api/game.py) but it returns 501
// — interactive two-player priority isn't built yet (see
// backend/ToDo_Backend.md "Multiplayer game session"). This just proves
// the route exists end-to-end and shows the server's "not yet" message.

import { startMultiplayer } from './api.js';

export function renderMultiplayerView(container) {
  container.innerHTML = `
    <div class="mp-stub">
      <h3>Multiplayer-Modus</h3>
      <p class="hint">
        Zwei menschliche Spieler mit Prioritäts-System (RULE 117) – noch in
        Arbeit. Das Backend kennt den Modus bereits, die interaktive
        Prioritäts-Schleife fehlt aber noch.
      </p>
      <button id="mp-try" type="button">Multiplayer testen</button>
      <p class="server-status" id="mp-status"></p>
    </div>
  `;
  container.querySelector('#mp-try').addEventListener('click', async () => {
    const st = container.querySelector('#mp-status');
    st.textContent = 'Frage Server …';
    st.className = 'server-status pending';
    const res = await startMultiplayer();
    if (res.status === 501) {
      st.textContent = res.data?.detail || 'Multiplayer ist noch nicht verfügbar.';
      st.className = 'server-status warning';
    } else if (res.status === 0) {
      st.textContent = 'Server nicht erreichbar.';
      st.className = 'server-status warning';
    } else {
      st.textContent = `Unerwartete Antwort (${res.status}).`;
      st.className = 'server-status';
    }
  });
}
