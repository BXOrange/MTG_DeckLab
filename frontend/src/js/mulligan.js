// The mulligan procedures a table can agree on (RULE 103.4) — the display
// names and the "what just happened to your hand" sentence, shared by the
// Goldfisch setup screen and the Multiplayer one. Kept in one place because
// the three styles differ in exactly what that sentence has to say, and two
// copies of that would drift. Localized via i18n.js (labels resolved at
// import; a language change reloads the page).
//
// Mirrors `backend/mtg_analyzer/services/game_session.py`'s MULLIGAN_STYLES.

import { t } from './i18n.js';

export const MULLIGAN_LABELS = {
  london: t('mulligan.style.london'),
  next7: t('mulligan.style.next7'),
  vancouver: t('mulligan.style.vancouver'),
  none: t('mulligan.style.none'),
};

/** Table sizes the lobby will open (`services/lobby.py`'s MIN/MAX_SEATS). */
export const SEAT_COUNTS = [2, 3, 4];

/**
 * What to tell a player who has just taken a mulligan.
 *
 * @param {{mulligan_style?: string}} setup The view's `setup` block.
 * @param {number} mulliganCount How many mulligans this seat has taken.
 * @param {number} bottomCount How many cards keeping must bottom now.
 * @param {number} handSize How many cards are in hand right now.
 */
export function mulliganText(setup, mulliganCount, bottomCount, handSize) {
  const nth = t('mulligan.nth', { n: mulliganCount });
  if (setup?.mulligan_style === 'vancouver') {
    // Vancouver pays for a mulligan in the draw rather than in bottoming,
    // and the scry that made it worth playing comes once everyone has kept.
    return t('mulligan.vancouverText', { nth, handSize });
  }
  if (bottomCount === 0) {
    return t('mulligan.noBottomText', { nth, handSize });
  }
  const n =
    bottomCount === 1 ? t('mulligan.bottomOne') : t('mulligan.bottomMany', { count: bottomCount });
  return t('mulligan.bottomText', { nth, handSize, n });
}
