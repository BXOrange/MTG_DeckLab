// "Profil" tab: the player name, persisted in a cookie (settings.js). The
// player name is the identity key player_assets.py stores uploaded token
// art / sleeves under (see connectionSettingsView.js), so this is the one
// field the rest of the app treats as "who you are".

import { getSettings, saveSettings } from './settings.js';

export function renderProfileView(container) {
  container.innerHTML = `
    <div class="connection-settings-panel">
      <h2>Profil</h2>

      <div class="deck-section">
        <label for="profile-name-input">Spielername</label>
        <input id="profile-name-input" type="text" placeholder="z.B. Alex" />
      </div>

      <div class="import-actions">
        <button id="save-profile-btn" type="button" class="primary">Speichern</button>
      </div>
      <p class="hint">
        Wird im Browser (Cookie) gespeichert — nicht serverseitig, ein anderer Browser/Rechner
        sieht ihn nicht. Eigene Token-Bilder und Karten-Sleeves (Tab "Einstellungen") sowie der
        Mehrspieler-Modus sind unter diesem Namen gespeichert.
      </p>
    </div>
  `;

  const nameInput = container.querySelector('#profile-name-input');
  const saveBtn = container.querySelector('#save-profile-btn');

  nameInput.value = getSettings().playerName;

  saveBtn.addEventListener('click', () => {
    const saved = saveSettings({ playerName: nameInput.value });
    nameInput.value = saved.playerName;
  });

  container.addEventListener('view-shown', () => {
    nameInput.value = getSettings().playerName;
  });
}
