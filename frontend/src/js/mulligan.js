// The mulligan procedures a table can agree on (RULE 103.4) — the German
// names and the "what just happened to your hand" sentence, shared by the
// Goldfisch setup screen and the Multiplayer one. Kept in one place because
// the three styles differ in exactly what that sentence has to say, and two
// copies of that would drift.
//
// Mirrors `backend/mtg_analyzer/services/game_session.py`'s MULLIGAN_STYLES.

export const MULLIGAN_LABELS = {
  london: 'London-Mulligan (neue 7, dann N Karten unterlegen)',
  next7: 'Next 7 (neue 7, nichts unterlegen)',
  vancouver: 'Vancouver (jeweils eine Karte weniger, danach Hellsicht 1)',
  none: 'Kein Mulligan (Starthand wird behalten)',
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
  const nth = `Mulligan Nr. ${mulliganCount}`;
  if (setup?.mulligan_style === 'vancouver') {
    // Vancouver pays for a mulligan in the draw rather than in bottoming,
    // and the scry that made it worth playing comes once everyone has kept.
    return `${nth}: ${handSize} Karten gezogen — jeder Mulligan zieht eine Karte weniger. Nach dem Behalten folgt Hellsicht 1 (sobald alle behalten haben).`;
  }
  if (bottomCount === 0) {
    return `${nth}: neue ${handSize} Karten gezogen. Kein Unterlegen nötig — die Hand bleibt bei ${handSize} Karten.`;
  }
  return `${nth}: neue ${handSize} Karten gezogen. Beim Behalten ${
    bottomCount === 1 ? 'muss 1 Karte' : `müssen ${bottomCount} Karten`
  } unten in die Bibliothek gelegt werden.`;
}
