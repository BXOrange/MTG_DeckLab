import { createGameAudio } from './src/js/gameAudio.js';
const audio = createGameAudio();
const volume = document.querySelector('#volume');
volume.value = audio.volume;
volume.addEventListener('input', () => audio.setVolume(volume.value));
document.querySelector('#mute').addEventListener('click', () => {
  audio.setEnabled(false);
  document.querySelector('#status').textContent = 'Stumm. Eine Hörprobe aktiviert den Ton wieder.';
});
for (const button of document.querySelectorAll('[data-kind]')) {
  button.addEventListener('click', async () => {
    audio.setEnabled(true);
    if (!await audio.unlock()) {
      document.querySelector('#status').textContent = 'Audio konnte im Browser nicht gestartet werden.';
      return;
    }
    audio.stop();
    const colors = [...document.querySelectorAll('#colors input:checked')].map((el) => el.value);
    audio.play({ kind: button.dataset.kind, amount: 6, card: { colors, type_line: document.querySelector('#type').value } });
    document.querySelector('#status').textContent = `${button.textContent}${button.dataset.kind === 'cast' ? ` · ${document.querySelector('#type').value}` : ''} · ${colors.join(' / ') || 'farblos'}`;
  });
}
