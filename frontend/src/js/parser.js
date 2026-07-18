// Client-side decklist parser.
//
// The UI provides three separate input sections — Commander, Mainboard,
// Sideboard — and assignment is determined by which section a card was
// entered under, not by inline text headers. Each section accepts plain
// card lines: "1 Sol Ring", "4x Mountain", with optional "*TAG*" markers
// and trailing set/collector info like "(LTR) 123" stripped.
//
// This runs entirely in the browser; there is no backend card database
// yet, so validation is limited to structural Commander rules (100
// cards, singleton, one legal commander count) rather than real card
// legality/color-identity checks.

const BASIC_LAND_NAMES = new Set([
  'Plains', 'Island', 'Swamp', 'Mountain', 'Forest', 'Wastes',
  'Snow-Covered Plains', 'Snow-Covered Island', 'Snow-Covered Swamp',
  'Snow-Covered Mountain', 'Snow-Covered Forest', 'Snow-Covered Wastes',
]);

const CARD_LINE_RE = /^(\d+)\s*[xX]?\s+(.+)$/;
const SET_SUFFIX_RE = /\s*[[(][A-Za-z0-9]{2,6}[)\]]\s*[\dA-Za-z-]*\s*$/;
const TAG_RE = /\s*\*([A-Za-z]+)\*/g;
// Foil/star markers some exports append to a name ("Sol Ring ★"). Not
// part of the card name and they break resolution, so strip them.
const STAR_RE = /[★☆]/g;

/**
 * Parses a single section's raw text into card lines.
 * @param {string} rawText
 * @returns {{cards: {name: string, qty: number}[], parseErrors: string[]}}
 */
function parseCardLines(rawText) {
  const lines = (rawText || '').split(/\r?\n/);
  const cards = [];
  const parseErrors = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || line.startsWith('//')) continue;

    const match = line.match(CARD_LINE_RE);
    if (!match) {
      parseErrors.push(`Zeile konnte nicht gelesen werden: "${rawLine}"`);
      continue;
    }

    const qty = parseInt(match[1], 10);
    let name = match[2].trim();
    name = name.replace(TAG_RE, '').trim();
    name = name.replace(SET_SUFFIX_RE, '').trim();
    name = name.replace(STAR_RE, '').replace(/\s{2,}/g, ' ').trim();

    if (!name) {
      parseErrors.push(`Leerer Kartenname in Zeile: "${rawLine}"`);
      continue;
    }

    cards.push({ name, qty });
  }

  return { cards, parseErrors };
}

function mergeCards(cards) {
  const merged = new Map();
  for (const card of cards) {
    const key = card.name.toLowerCase();
    if (merged.has(key)) {
      merged.get(key).qty += card.qty;
    } else {
      merged.set(key, { ...card });
    }
  }
  return Array.from(merged.values());
}

/**
 * @param {{commanderText?: string, mainboardText?: string, sideboardText?: string, isCube?: boolean}} sections
 *   `isCube` marks this as a card pool (e.g. a curated "staples" list) rather
 *   than a real Commander deck, skipping the structural checks below —
 *   mirrors `models/deck.py`'s `is_cube` / `parser/deckliste_parser.py`.
 * @returns {{
 *   commanders: {name: string, qty: number}[],
 *   mainDeck: {name: string, qty: number}[],
 *   allCards: {name: string, qty: number}[],
 *   sideboard: {name: string, qty: number}[],
 *   totalCount: number,
 *   parseErrors: string[],
 *   validation: {isLegal: boolean, errors: string[], warnings: string[]},
 * }}
 */
export function parseDeckSections({ commanderText = '', mainboardText = '', sideboardText = '', isCube = false } = {}) {
  const commanderParsed = parseCardLines(commanderText);
  const mainboardParsed = parseCardLines(mainboardText);
  const sideboardParsed = parseCardLines(sideboardText);

  const parseErrors = [
    ...commanderParsed.parseErrors,
    ...mainboardParsed.parseErrors,
    ...sideboardParsed.parseErrors,
  ];

  const commanders = mergeCards(commanderParsed.cards);
  const mainDeck = mergeCards(mainboardParsed.cards);
  const sideboard = mergeCards(sideboardParsed.cards);
  const allCards = mergeCards([...commanderParsed.cards, ...mainboardParsed.cards]);
  const totalCount = allCards.reduce((sum, c) => sum + c.qty, 0);

  return {
    commanders,
    mainDeck,
    allCards,
    sideboard,
    totalCount,
    parseErrors,
    validation: validateCommanderDeck(allCards, commanders, totalCount, isCube),
  };
}

function validateCommanderDeck(allCards, commanders, totalCount, isCube) {
  if (isCube) return { isLegal: true, errors: [], warnings: [] };

  const errors = [];
  const warnings = [];

  if (commanders.length === 0) {
    warnings.push('Kein Commander erkannt (im Abschnitt "Commander" eintragen).');
  } else if (commanders.length > 2) {
    errors.push(`Zu viele Commander erkannt (${commanders.length}). Erlaubt sind 1 (oder 2 mit Partner).`);
  }

  if (totalCount !== 100) {
    errors.push(`Deck hat ${totalCount} Karten, erwartet werden 100 (inkl. Commander).`);
  }

  for (const card of allCards) {
    if (card.qty > 1 && !BASIC_LAND_NAMES.has(card.name)) {
      errors.push(`"${card.name}" ist ${card.qty}x im Deck – Commander ist Singleton (außer Basic Lands).`);
    }
  }

  return { isLegal: errors.length === 0, errors, warnings };
}

export const SAMPLE_COMMANDER = `1 Krenko, Mob Boss
`;

export const SAMPLE_MAINBOARD = `1 Sol Ring
1 Arcane Signet
1 Mind Stone
1 Fellwar Stone
1 Goblin Bombardment
1 Purphoros, God of the Forge
1 Skullclamp
1 Thornbite Staff
1 Goblin Chieftain
1 Goblin King
1 Warren Instigator
1 Siege-Gang Commander
1 Wort, Boggart Auntie
1 Tin Street Kingpin
1 Goblin Matron
1 Goblin Recruiter
1 Muxus, Goblin Grandee
1 Conspicuous Snoop
1 Reckless Bushwhacker
1 Hordeling Outburst
1 Dragon Fodder
1 Foundry Street Denizen
1 Goblin Rabblemaster
1 Impact Tremors
1 Fiery Emancipation
1 Shared Animosity
1 Coat of Arms
1 Goblin Warchief
1 Krenko's Command
1 Mogg War Marshal
1 Legion Loyalist
1 Goblin Piledriver
1 Squee, Goblin Nabob
1 Kiki-Jiki, Mirror Breaker
1 Chaos Warp
1 Lightning Bolt
1 Swiftfoot Boots
62 Mountain
`;

export const SAMPLE_SIDEBOARD = `1 Negate
1 Pyroblast
`;
