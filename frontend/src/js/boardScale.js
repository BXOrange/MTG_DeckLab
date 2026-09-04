// Whole-board zoom: one app-wide preference (not per game mode) applied to
// every `gameBoardView.js` instance (Goldfisch/Solo/Replay/Multiplayer all
// create their own), so it lives here rather than inside that module. The
// control itself sits at the bottom of the sidebar (`app.js`), not in the
// board's own rail, since it's app chrome rather than something specific to
// the game in progress.
import { getCookie, setCookie } from './cookies.js';

// 100 is the CSS-authored size; the min/max keep the board from shrinking
// past legibility or growing past what any viewport can usefully show.
export const BOARD_SCALE_MIN = 75;
export const BOARD_SCALE_MAX = 150;
export const BOARD_SCALE_STEP = 10;

function clamp(n) {
  return Math.min(BOARD_SCALE_MAX, Math.max(BOARD_SCALE_MIN, n));
}

let scale = clamp(parseInt(getCookie('gf_board_scale'), 10) || 100);
const listeners = new Set();

export function getBoardScale() {
  return scale;
}

function setScale(next) {
  const clamped = clamp(next);
  if (clamped === scale) return;
  scale = clamped;
  setCookie('gf_board_scale', String(scale), 365);
  listeners.forEach((fn) => fn(scale));
}

export function stepBoardScale(direction) {
  setScale(scale + direction * BOARD_SCALE_STEP);
}

export function resetBoardScale() {
  setScale(100);
}

/** @param {(scale: number) => void} fn */
export function onBoardScaleChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
