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
//
// parseMoxfieldExport()/isCommanderCandidate()/canPairAsCommanders() below
// are the exception to "assignment is by section, not inline headers":
// together they let deckImportView.js split a whole pasted Moxfield export
// (one section-less blob + a "SIDEBOARD:" header) into the three sections
// above. Moxfield's export prints no header for the commander(s) at all,
// so telling them apart from the mainboard needs real card data (is this
// legendary / does it say "can be your commander" / Partner) — that's why
// this part isn't as "pure text" as the rest of this module; the actual
// card lookup stays deckImportView.js's job (it already owns
// resolveCardImages), these two just make the yes/no call once resolved.

import { t } from './i18n.js';

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

// Moxfield's own "SIDEBOARD:" export header — the only section label its
// plain-text export actually contains (see parseMoxfieldExport below).
const SIDEBOARD_HEADER_RE = /^sideboard:?$/i;

function stripCardNameNoise(rawName) {
  let name = rawName.trim();
  name = name.replace(TAG_RE, '').trim();
  name = name.replace(SET_SUFFIX_RE, '').trim();
  name = name.replace(STAR_RE, '').replace(/\s{2,}/g, ' ').trim();
  return name;
}

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
    const name = stripCardNameNoise(match[2]);

    if (!name) {
      parseErrors.push(`Leerer Kartenname in Zeile: "${rawLine}"`);
      continue;
    }

    cards.push({ name, qty });
  }

  return { cards, parseErrors };
}

/**
 * Splits a Moxfield plain-text export (one card per line, "N Name (SET)
 * 123" with an optional trailing foil marker, a blank line, then a
 * "SIDEBOARD:" header) into its pre-sideboard "body" lines and its
 * sideboard text. The body still mixes commander(s) and mainboard —
 * Moxfield prints no header for the commander at all — see
 * `isCommanderCandidate`/`canPairAsCommanders` for how deckImportView.js
 * tells them apart using real card data, and `buildMoxfieldSections` for
 * turning a resolved commander count back into the three section texts.
 * @param {string} rawText
 * @returns {{bodyLines: {rawLine: string, name: string}[], sideboardText: string}}
 */
export function parseMoxfieldExport(rawText) {
  const allLines = (rawText || '').split(/\r?\n/);
  const bodyLines = [];
  const sideboardLines = [];
  let inSideboard = false;

  for (const rawLine of allLines) {
    if (!inSideboard && SIDEBOARD_HEADER_RE.test(rawLine.trim())) {
      inSideboard = true;
      continue;
    }
    (inSideboard ? sideboardLines : bodyLines).push(rawLine);
  }

  const body = bodyLines
    .map((rawLine) => rawLine.trim())
    .filter((line) => line && !line.startsWith('#') && !line.startsWith('//'))
    .map((line) => {
      const match = line.match(CARD_LINE_RE);
      return { rawLine: line, name: match ? stripCardNameNoise(match[2]) : '' };
    })
    .filter((l) => l.name);

  return {
    bodyLines: body,
    sideboardText: sideboardLines.map((l) => l.trim()).filter(Boolean).join('\n'),
  };
}

/**
 * Turns a `parseMoxfieldExport` result plus a resolved commander count
 * back into the three section texts the import textareas use.
 * @param {{bodyLines: {rawLine: string}[], sideboardText: string}} parsed
 * @param {number} commanderCount
 * @returns {{commanderText: string, mainboardText: string, sideboardText: string}}
 */
export function buildMoxfieldSections({ bodyLines, sideboardText }, commanderCount) {
  return {
    commanderText: bodyLines.slice(0, commanderCount).map((l) => l.rawLine).join('\n'),
    mainboardText: bodyLines.slice(commanderCount).map((l) => l.rawLine).join('\n'),
    sideboardText,
  };
}

/**
 * Whether a resolved card dict (see cardImages.js's `getResolvedCard`/
 * `resolveCardImages`) is eligible to be a Commander at all (RULE 903.3):
 * a legendary creature, or a card whose oracle text carries the explicit
 * "can be your commander" exception WotC prints on non-legendary-creature
 * commander-legal cards (some planeswalkers, e.g. Comet, Stellar Pup).
 * Doesn't check color identity/ban list/deck legality — just "could this
 * card occupy the Commander zone", which is all Moxfield-import splitting
 * needs to tell a commander line from an ordinary mainboard line.
 * @param {object | null | undefined} card
 * @returns {boolean}
 */
export function isCommanderCandidate(card) {
  if (!card) return false;
  if (card.is_legendary && card.is_creature) return true;
  return (card.oracle_text || '').toLowerCase().includes('can be your commander');
}

/**
 * Whether two commander-candidate cards may legally serve as co-
 * commanders together — mirrors the backend's
 * `commander_legality._can_pair` (Partner / "Partner with X"; doesn't
 * (yet) model the Background mechanic, matching that same backend gap).
 * @param {object} cardA
 * @param {object} cardB
 * @returns {boolean}
 */
export function canPairAsCommanders(cardA, cardB) {
  if (cardA.partner_with || cardB.partner_with) {
    return (
      !!cardA.partner_with &&
      !!cardB.partner_with &&
      cardA.partner_with.trim().toLowerCase() === cardB.name.trim().toLowerCase() &&
      cardB.partner_with.trim().toLowerCase() === cardA.name.trim().toLowerCase()
    );
  }
  return !!(cardA.has_partner && cardB.has_partner);
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
    warnings.push(t('parser.noCommander'));
  } else if (commanders.length > 2) {
    errors.push(t('parser.tooManyCommanders', { count: commanders.length }));
  }

  if (totalCount !== 100) {
    errors.push(t('parser.wrongTotal', { count: totalCount }));
  }

  for (const card of allCards) {
    if (card.qty > 1 && !BASIC_LAND_NAMES.has(card.name)) {
      errors.push(t('parser.notSingleton', { name: card.name, qty: card.qty }));
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
