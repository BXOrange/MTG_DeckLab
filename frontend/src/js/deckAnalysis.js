// Static, numeric deck statistics for the "Deck analysieren" tab —
// mana curve, card-type distribution, land archetypes, mana-value
// averages, opening-hand land odds, color-pip-vs-source counts, and a
// "Command Zone" deckbuilding-template breakdown (Lands/Ramp/Card
// Advantage/Targeted Disruption/Mass Disruption/Plan Cards). Pure,
// DOM-free functions operating on already-resolved `Card` dicts (see
// cardImages.js), same data every other view already fetches — no new
// backend endpoint.
//
// This is presentation-only: it classifies cards (mana rock / dork /
// ramp spell / land archetype) by regexing their oracle text as a
// *display heuristic*, not the security-boundary oracle-effect parser
// under backend/mtg_analyzer/parser/oracle/ (docs/09) — nothing here
// becomes executable game behaviour, so a wrong guess just mislabels a
// chart, it can't corrupt a game. Expect occasional misclassifications
// on unusually worded cards.

//: A card's own mana ability, e.g. "{T}: Add {G}.", "Add one mana of any
//: color.", "Add {C}{C}.". Used to recognize mana rocks/dorks and, when
//: NOT on a permanent, one-shot ritual effects (Dark Ritual). Deliberately
//: checked only once `isTreasureGenerator` has ruled a card out (see
//: there): a card that just *grants an ability to Treasure tokens*
//: ("Treasures you control have '{T}, Sacrifice this artifact: Add two
//: mana…'", Goldspan Dragon) reprints that mana text on itself without
//: having any mana ability of its own — matching this regex is not
//: sufficient on its own to call a card a mana source.
import { t } from './i18n.js';

const MANA_ABILITY_RE = /\badd\s+(\{[wubrgcsx0-9/]+\}|(one|two|three|x)\s+mana|mana\b)/i;

//: "Search your library for ... land ... battlefield/hand" — land-tutor
//: ramp SPELLS (Rampant Growth, Cultivate, Nature's Lore, …). Distinct
//: from `isFetchLand` below, which classifies actual Land-typed cards.
const LAND_FETCH_RAMP_RE = /search your library for[^.]*\bland\b[^.]*\b(battlefield|hand)\b/i;

//: "create a/two/… Treasure token(s)" — Treasure-making cards (Storm-Kiln
//: Artist, Malcolm, Keen-Eyed Navigator, Goldspan Dragon, …) are a burst/
//: conditional resource like a ritual, not a guaranteed recurring mana
//: source: the token has to actually be created (often trigger-gated) and
//: is consumed (sacrificed) the moment it's used. Requires "create" near
//: "Treasure token" so a card that only *uses*/*hates* Treasures (e.g.
//: "Destroy target Treasure") doesn't false-positive.
const TREASURE_MAKER_RE = /\bcreate[s]?\b[^.]{0,60}\btreasure token/i;

//: "Its controller creates ..." / "that player creates ..." — a Treasure
//: handed to an effect's TARGET (e.g. a "soft counter" cycle: "Counter
//: target noncreature spell. Its controller creates two Treasure
//: tokens.", An Offer You Can't Refuse), not a resource for this card's
//: own controller — excluded so the card is judged by its actual effect
//: (here, a counterspell) instead of "Ramp".
const TREASURE_TO_TARGET_RE = /\b(its controller|its owner|that player) creates?\b[^.]{0,60}\btreasure token/i;

//: "Enchant land"/"Enchant Forest"/… — an Aura attached to a land (Wild
//: Growth, Utopia Sprawl, Fertile Ground, Overgrowth, …), whose granted
//: ability (checked separately via `producesMana`) makes the enchanted
//: land tap for extra/different mana. Once resolved it's a recurring
//: source exactly like a mana rock/dork, not a one-shot burst.
const ENCHANT_LAND_RE = /\benchant\s+(land|plains|island|swamp|mountain|forest)\b/i;

//: Strips parenthetical reminder text ("(This creature can't attack.)",
//: "(They're artifacts with '{T}, Sacrifice this token: Add one mana of
//: any color.')", …) before any heuristic below sees it — reminder text
//: explains rules generically and routinely contains phrases (mana
//: abilities, "can't attack", …) that describe something other than
//: *this* card's own effect, which would otherwise false-positive a
//: classifier looking for that exact phrase in the card's real text.
function oracleText(card) {
  return (card?.oracle_text || '').replace(/\([^)]*\)/g, ' ');
}

function producesMana(card) {
  return MANA_ABILITY_RE.test(oracleText(card));
}

/** Creates Treasure tokens (a burst/conditional mana resource, not a recurring source). */
export function isTreasureGenerator(card) {
  const t = oracleText(card);
  return !card.is_land && TREASURE_MAKER_RE.test(t) && !TREASURE_TO_TARGET_RE.test(t);
}

//: The cost text immediately in front of a "…: Add …" mana ability —
//: stops at the previous sentence/newline, so a cost-shape check below
//: looks only at *this* ability's cost, not an unrelated "Sacrifice ~:
//: Draw a card" ability elsewhere on the same permanent (Mind Stone still
//: has a plain, repeatable "{T}: Add {C}.").
function manaAbilityCostText(card) {
  const match = oracleText(card).match(/([^.\n]*?):\s*add\s+(?:\{|one\b|two\b|three\b|x\b|mana\b)/i);
  return match ? match[1] : '';
}

function manaAbilityActivationCost(card) {
  const cost = manaAbilityCostText(card);
  return [...cost.matchAll(/\{(\d+)\}/g)].reduce((total, match) => total + Number(match[1]), 0);
}

function manaAbilityMinimumLandCount(card) {
  const match = oracleText(card).match(
    /\bactivate(?: this ability)? only if you control (one|two|three|four|five|six|seven|eight|nine|ten|\d+) or more lands\b/i
  );
  if (!match) return 0;
  const number = Number(match[1]);
  if (Number.isFinite(number)) return number;
  return ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'].indexOf(
    match[1].toLowerCase()
  ) + 1;
}

/**
 * A mana source consumed the instant it's used — paid for by sacrificing
 * itself (Lotus Petal, Lion's Eye Diamond) or by exiling itself from hand
 * (Elvish/Simian Spirit Guide) — mechanically a one-shot ritual burst, not
 * a per-turn source, whatever the card's own type line says.
 */
export function isOneShotManaSource(card) {
  const cost = manaAbilityCostText(card);
  if (!cost) return false;
  return /\bsacrifice\b/i.test(cost) || (/\bexile\b/i.test(cost) && /\bfrom your hand\b/i.test(cost));
}

/** A repeatable artifact mana source (Sol Ring, signets, …). */
export function isManaRock(card) {
  return (
    !card.is_land &&
    !card.is_creature &&
    !isTreasureGenerator(card) &&
    !isOneShotManaSource(card) &&
    /\bartifact\b/i.test(card.type_line) &&
    producesMana(card)
  );
}

/** A repeatable creature mana source (Llanowar Elves, Birds of Paradise, …). */
export function isManaDork(card) {
  return (
    !card.is_land && card.is_creature && !isTreasureGenerator(card) && !isOneShotManaSource(card) && producesMana(card)
  );
}

/** An Aura enchanting a land that grants it an extra mana ability (Wild Growth, Utopia Sprawl, …). */
export function isManaLandAura(card) {
  return (
    !card.is_land &&
    !card.is_creature &&
    !isTreasureGenerator(card) &&
    !isOneShotManaSource(card) &&
    ENCHANT_LAND_RE.test(oracleText(card)) &&
    producesMana(card)
  );
}

/**
 * A non-permanent that accelerates: a land-tutor ("landFetch", Cultivate)
 * or a one-shot mana burst ("ritual", Dark Ritual, Jeska's Will) —
 * distinct because only the former keeps paying off turn after turn (see
 * `simulateManaCurve`).
 * @returns {'landFetch'|'ritual'|null}
 */
export function rampSpellKind(card) {
  if (card.is_land || card.is_creature || isManaRock(card) || isTreasureGenerator(card) || isManaLandAura(card)) {
    return null;
  }
  const isSpellLike = card.is_instant || card.is_sorcery || /\b(artifact|enchantment)\b/i.test(card.type_line);
  if (!isSpellLike) return null;
  if (LAND_FETCH_RAMP_RE.test(oracleText(card))) return 'landFetch';
  if ((card.is_instant || card.is_sorcery) && producesMana(card)) return 'ritual';
  return null;
}

/** How much mana one activation of a source adds — best-effort from its own text, default 1. */
export function manaProduced(card) {
  const text = oracleText(card);
  const symbols = text.match(/\badd\s+((?:\{[^}]+\})+)/i);
  if (symbols) {
    const count = (symbols[1].match(/\{[^}]+\}/g) || []).length;
    return Math.max(1, count);
  }
  if (/\badd\s+three\b/i.test(text)) return 3;
  if (/\badd\s+two\b/i.test(text)) return 2;
  return 1;
}

//: type_line/flag → display bucket. A card can land in several (an
//: Artifact Creature counts in both), matching how deck-building tools
//: (Moxfield/Archidekt) usually total types.
export const TYPE_BUCKETS = [
  { key: 'creature', label: t('da.type.creature'), test: (c) => c.is_creature },
  { key: 'planeswalker', label: t('da.type.planeswalker'), test: (c) => /\bplaneswalker\b/i.test(c.type_line) },
  { key: 'battle', label: t('da.type.battle'), test: (c) => /\bbattle\b/i.test(c.type_line) },
  { key: 'land', label: t('da.type.land'), test: (c) => c.is_land },
  { key: 'artifact', label: t('da.type.artifact'), test: (c) => /\bartifact\b/i.test(c.type_line) },
  { key: 'enchantment', label: t('da.type.enchantment'), test: (c) => /\benchantment\b/i.test(c.type_line) },
  { key: 'instant', label: t('da.type.instant'), test: (c) => c.is_instant },
  { key: 'sorcery', label: t('da.type.sorcery'), test: (c) => c.is_sorcery },
];

//: The five basic land types — a nonbasic land naming 3+ of these is a
//: Triome (Ikoria); naming exactly 2 is the common "dual" shape shared by
//: shock/check/pain/fast/slow/battle lands.
const BASIC_LAND_TYPE_NAMES = ['Plains', 'Island', 'Swamp', 'Mountain', 'Forest'];

function basicLandTypeCount(typeLine) {
  return BASIC_LAND_TYPE_NAMES.filter((name) => new RegExp(`\\b${name}\\b`).test(typeLine)).length;
}

//: A modal DFC whose BACK face is a land (Zendikar Rising's spell//land
//: cycle: Malakir Rebirth // Malakir Mire, Sea Gate Restoration // Sea
//: Gate, Reborn, …). The Card model is front-face-first — `card.is_land`/
//: `card.type_line`/`card.oracle_text` only ever describe the front
//: spell face (see backend `card_from_scryfall_data`'s docstring) — so
//: these never satisfy `card.is_land` and would otherwise never reach
//: the land-archetype breakdown at all, even though most decks count
//: them as (flexible) lands. `card.back_type_line`/`back_oracle_text`
//: hold the actual land face's data.
function isMdfcLand(card) {
  return card.layout === 'modal_dfc' && /\bland\b/i.test(card.back_type_line || '');
}

//: Well-known nonbasic-land cycles (RULE 305), classified off oracle text
//: by their defining ability. Order matters — first match wins, most
//: specific first — since a card is filed under exactly one archetype
//: here (unlike TYPE_BUCKETS, which allows several).
const LAND_ARCHETYPES = [
  { key: 'basic', label: t('da.land.basic'), test: (c) => /\bbasic\b/i.test(c.type_line) },
  {
    key: 'fetch',
    label: t('da.land.fetch'),
    // Already gated to is_land: a land that sacrifices itself to search
    // the library is, in practice, always a fetchland (Onslaught-style
    // "Search your library for a Plains or Island card" never says
    // "land" explicitly, so that word can't be required here).
    test: (c) => /\bsacrifice\b/i.test(oracleText(c)) && /search your library for/i.test(oracleText(c)),
  },
  {
    key: 'canopy',
    label: t('da.land.horizon'),
    test: (c) => /\bsacrifice\b/i.test(oracleText(c)) && /draw a card/i.test(oracleText(c)),
  },
  {
    key: 'bounce',
    label: t('da.land.bounce'),
    test: (c) => /return a land you control to its owner's hand/i.test(oracleText(c)),
  },
  {
    key: 'manland',
    label: t('da.land.creature'),
    test: (c) => /\bbecomes? a\b[^.]*\bcreature\b/i.test(oracleText(c)),
  },
  { key: 'triome', label: t('da.land.triome'), test: (c) => basicLandTypeCount(c.type_line) >= 3 },
  {
    key: 'pain',
    label: t('da.land.pain'),
    test: (c) => /deals? 1 damage to you/i.test(oracleText(c)),
  },
  {
    key: 'shock',
    label: t('da.land.shock'),
    test: (c) => /pay 2 life/i.test(oracleText(c)) && /\btapped\b/i.test(oracleText(c)),
  },
  {
    key: 'check',
    label: t('da.land.check'),
    test: (c) => /tapped unless you control/i.test(oracleText(c)) && !/two or (more|fewer)/i.test(oracleText(c)),
  },
  { key: 'fast', label: t('da.land.fast'), test: (c) => /two or fewer other lands/i.test(oracleText(c)) },
  { key: 'slow', label: t('da.land.slow'), test: (c) => /two or more other lands/i.test(oracleText(c)) },
  { key: 'battle', label: t('da.land.battle'), test: (c) => /two or more basic lands/i.test(oracleText(c)) },
  {
    // Checked after every mana-producing cycle above (a fetchland has no
    // "Add" text of its own either, so it must be filtered out by the
    // `fetch` entry first) — this is specifically a land with NO mana
    // ability at all (Maze of Ith, Strip Mine, Rishadan Port, Wasteland
    // is excluded since it does add {C}), as opposed to `other` below,
    // which is the catch-all for mana-producing nonbasics that don't fit
    // a recognized cycle.
    key: 'utility',
    label: t('da.land.utility'),
    test: (c) => !producesMana(c),
  },
   { key: 'mdfc_land', label: t('da.land.mdfc'), test: isMdfcLand },
  {
    key: 'conditional_tapped',
    label: t('da.land.otherTapped'),
    test: (c) => /enters?( the battlefield)? tapped/i.test(oracleText(c)),
  },
  { key: 'other', label: t('da.land.other'), test: () => true },
];

/** Which `LAND_ARCHETYPES` entry a (land) card falls under — first match wins. */
export function landArchetype(card) {
  return LAND_ARCHETYPES.find((a) => a.test(card));
}

//: "The Command Zone" podcast's popular Commander deck-building template
//: (roughly: ~36 lands, ~10 ramp, ~10 card draw, ~10 targeted removal/
//: counters, ~2-3 board wipes, the rest "plan" cards that actually execute
//: the deck's strategy). Every nonland card is filed into exactly one
//: bucket by `commandZoneCategory` below, most-specific first — ramp
//: (reusing the mana-source classification above), then mass disruption,
//: then targeted disruption, then card draw, else "plan" — so a board
//: wipe with a "draw a card" rider lands under Mass Disruption, not Card
//: Advantage, and a mana rock that also draws a card stays Ramp.

//: "Draw a/two/X card(s)" anywhere in the text — a broad net that also
//: catches "whenever you draw a card, ..." triggers; good enough for a
//: display heuristic, not perfectly precise.
const CARD_DRAW_RE = /\bdraws?\b[^.]{0,40}\bcards?\b/i;

//: "Target opponent/player discards ..." — single-target hand disruption
//: (Mind Rot's little cousin, Duress, …). Distinct from `MASS_DISCARD_RE`
//: below ("each player/opponent discards"), which hits every opponent at
//: once and stays filed under Mass Disruption.
const TARGETED_DISCARD_RE = /\btarget (opponent|player) discards?\b/i;

//: Sub-bucket of "Card Advantage" — first match wins.
const CARD_ADVANTAGE_KINDS = [
  { key: 'card_draw', label: t('da.cardAdv.card_draw'), test: (c) => CARD_DRAW_RE.test(oracleText(c)) },
  { key: 'opponent_discard', label: t('da.cardAdv.opponent_discard'), test: (c) => TARGETED_DISCARD_RE.test(oracleText(c)) },
];

/** Which `CARD_ADVANTAGE_KINDS` entry (if any) a card falls under. */
export function cardAdvantageKind(card) {
  return CARD_ADVANTAGE_KINDS.find((k) => k.test(card))?.key ?? null;
}

//: "Counter target ... spell/ability" — a type restriction (noncreature,
//: enchantment/instant/or sorcery, activated/triggered, …) commonly sits
//: between "target" and "spell"/"ability" (An Offer You Can't Refuse:
//: "Counter target noncreature spell", Swan Song: "Counter target
//: enchantment, instant, or sorcery spell"), so this doesn't require them
//: adjacent — just within the same clause.
const COUNTERSPELL_RE = /\bcounter target\b[^.]{0,40}\b(spell|ability)\b/i;
const DESTROY_EXILE_TARGET_RE =
  /\b(destroy|exile)\s+target\b[^.]*\b(creature|permanent|artifact|enchantment|planeswalker|battle)\b/i;
const DAMAGE_TO_TARGET_RE = /\bdeals?\s+\d+\s+damage to (target|any target)\b/i;
const MINUS_TOUGHNESS_TARGET_RE = /target creature (gets|has)[^.]*-\d+\/-\d+/i;
const FIGHT_TARGET_RE = /\bfights?\s+target creature\b/i;
const BOUNCE_TARGET_RE = /\breturn target\b[^.]*\bto (its|their|your opponent's) owner'?s? hand\b/i;
const THREATEN_RE = /\bgain control of target creature\b/i;
const EDICT_RE = /\btarget (player|opponent) sacrifices? an?\b/i;
//: Deliberately doesn't match a bare "unless ... pays" — that phrase alone
//: also covers "you may draw a card unless that player pays {1}" (Rhystic
//: Study, Mystic Remora), which is a Card Advantage draw engine, not a
//: stax/prison restriction. Genuine tax effects pair the same phrase with
//: an explicit restriction (can't/costs more), already covered below.
//: The last alternative is the "opponents' permanents enter tapped" stax
//: shape (Blind Obedience: "Artifacts and creatures your opponents
//: control enter tapped.", Root Maze, …) — oracle wording varies between
//: "enter tapped" and the older "enter the battlefield tapped".
const PRISON_RE =
  /\b(can't attack|can't block|can't cast spells|can't activate|players can't|skip[^.]*(untap|draw|combat) step|spells cost \{\d+\} more|your opponents? control\b[^.]{0,20}\benters? (the battlefield )?tapped)\b/i;
const GRAVEYARD_HATE_RE = /\bexile\b[^.]*\bfrom (a|target player's|target opponent's|their) graveyard\b/i;

/** A single-target removal spell (destroy/exile/burn/-X-X/fight a creature or permanent). */
function isTargetedRemoval(card) {
  const t = oracleText(card);
  return (
    DESTROY_EXILE_TARGET_RE.test(t) ||
    DAMAGE_TO_TARGET_RE.test(t) ||
    MINUS_TOUGHNESS_TARGET_RE.test(t) ||
    FIGHT_TARGET_RE.test(t)
  );
}

//: Sub-bucket of "Targeted Disruption" (interaction aimed at a single
//: permanent/player) — first match wins, most specific first.
const TARGETED_DISRUPTION_KINDS = [
  { key: 'counterspell', label: t('da.targeted.counterspell'), test: (c) => COUNTERSPELL_RE.test(oracleText(c)) },
  { key: 'removal', label: t('da.targeted.removal'), test: isTargetedRemoval },
  { key: 'bounce', label: t('da.targeted.bounce'), test: (c) => BOUNCE_TARGET_RE.test(oracleText(c)) },
  { key: 'threaten', label: t('da.targeted.threaten'), test: (c) => THREATEN_RE.test(oracleText(c)) },
  { key: 'edict', label: t('da.targeted.edict'), test: (c) => EDICT_RE.test(oracleText(c)) },
  { key: 'graveyard_hate', label: t('da.targeted.graveyard_hate'), test: (c) => GRAVEYARD_HATE_RE.test(oracleText(c)) },
];

/** Which `TARGETED_DISRUPTION_KINDS` entry (if any) a card falls under. */
export function targetedDisruptionKind(card) {
  return TARGETED_DISRUPTION_KINDS.find((k) => k.test(card))?.key ?? null;
}

const BOARD_WIPE_RE =
  /\bdestroy all creatures\b|\beach creature (is destroyed|gets?|has)[^.]*-\d+\/-\d+|\bdeals?\s+\d+\s+damage to each creature\b|\ball creatures (get|gets|have) -\d+\/-\d+\b/i;
const MASS_BOUNCE_RE = /\breturn all creatures\b/i;
const MASS_REMOVAL_OTHER_RE = /\bdestroy all (artifacts|enchantments|planeswalkers)\b/i;
const MASS_DISCARD_RE = /\beach (player|opponent) discards\b/i;
const MASS_SACRIFICE_RE = /\beach (player|opponent) sacrifices\b/i;
const MASS_GRAVEYARD_HATE_RE = /\bexile[^.]*\b(all|each player's|all players'|each opponent's) graveyards?\b/i;

//: Sub-bucket of "Mass Disruption" (board wipes and other every-
//: opponent/symmetric effects) — first match wins, same convention as
//: `TARGETED_DISRUPTION_KINDS`.
const MASS_DISRUPTION_KINDS = [
  { key: 'board_wipe', label: t('da.mass.board_wipe'), test: (c) => BOARD_WIPE_RE.test(oracleText(c)) },
  { key: 'prison', label: t('da.mass.prison'), test: (c) => PRISON_RE.test(oracleText(c)) },
  { key: 'mass_bounce', label: t('da.mass.mass_bounce'), test: (c) => MASS_BOUNCE_RE.test(oracleText(c)) },
  {
    key: 'mass_removal_other',
    label: t('da.mass.mass_removal_other'),
    test: (c) => MASS_REMOVAL_OTHER_RE.test(oracleText(c)),
  },
  { key: 'mass_discard', label: t('da.mass.mass_discard'), test: (c) => MASS_DISCARD_RE.test(oracleText(c)) },
  { key: 'mass_sacrifice', label: t('da.mass.mass_sacrifice'), test: (c) => MASS_SACRIFICE_RE.test(oracleText(c)) },
  {
    key: 'graveyard_hate_mass',
    label: t('da.mass.graveyard_hate_mass'),
    test: (c) => MASS_GRAVEYARD_HATE_RE.test(oracleText(c)),
  },
];

/** Which `MASS_DISRUPTION_KINDS` entry (if any) a card falls under. */
export function massDisruptionKind(card) {
  return MASS_DISRUPTION_KINDS.find((k) => k.test(card))?.key ?? null;
}

//: The six Command Zone template buckets (lands handled separately by the
//: caller, since it's already gated on `card.is_land` there).
const COMMAND_ZONE_CATEGORIES = [
  { key: 'lands', label: t('da.cz.lands') },
  { key: 'ramp', label: t('da.cz.ramp') },
  { key: 'card_advantage', label: t('da.cz.card_advantage') },
  { key: 'targeted_disruption', label: t('da.cz.targeted_disruption') },
  { key: 'mass_disruption', label: t('da.cz.mass_disruption') },
  { key: 'plan', label: t('da.cz.plan') },
];

/**
 * A nonland card's Command Zone bucket + sub-kind (if any). `isRamp` is
 * passed in by `analyzeDeck`, which already runs the fuller mana-source
 * classification above (mana rock/dork/land aura/land-tutor/ritual/
 * Treasure) — re-deriving it here would just duplicate that logic.
 * @returns {{key: string, subKey: string|null}}
 */
export function commandZoneCategory(card, isRamp) {
  if (isRamp) return { key: 'ramp', subKey: null };
  const massKind = massDisruptionKind(card);
  if (massKind) return { key: 'mass_disruption', subKey: massKind };
  const targetedKind = targetedDisruptionKind(card);
  if (targetedKind) return { key: 'targeted_disruption', subKey: targetedKind };
  const advantageKind = cardAdvantageKind(card);
  if (advantageKind) return { key: 'card_advantage', subKey: advantageKind };
  return { key: 'plan', subKey: null };
}

//: "Search your library for ... card" — general tutor effects (Demonic
//: Tutor, Vampiric Tutor, Enlightened Tutor, Worldly Tutor, a creature's
//: land-tutor ETB, …), whatever they fetch to (hand/battlefield/top of
//: library/graveyard). Excludes lands themselves so an actual fetchland
//: (Flooded Strand: "Search your library for a(n) ... card") isn't
//: counted as a tutor — that's already its own Land-Archetype above.
//: Deliberately overlaps with the Ramp bucket (a land-tutor spell like
//: Rampant Growth is still tutoring, just for a land) rather than
//: excluding it — this is a raw count, not a mutually-exclusive bucket.
const TUTOR_RE = /\bsearch(es)? your library for[^.]*\bcard\b/i;

/** A general tutor effect (searches the library for a specific card). */
export function isTutor(card) {
  return !card.is_land && TUTOR_RE.test(oracleText(card));
}

// --- Commander Brackets (wizards.com's Beta power-level system) -----------
//
// A 5-tier scale (1 Exhibition … 5 cEDH) players use to set expectations
// before a game. Of its four checkable criteria (Game Changers, Mass
// Land Denial, Extra Turns, Tutors), only the first three are even
// theoretically detectable from a decklist — WotC dropped tutors from
// the system in their Oct 2025 update ("remove the tutor restrictions
// ... and rely on Game Changers to catch the most efficient tutors").
// Two-card infinite combos require cross-card knowledge. They are matched
// against the local Commander Spellbook snapshot in analyzeView.js; only
// explicitly infinite produced features can affect the bracket heuristic.

//: The official Game Changers list — unlike every other heuristic in
//: this file, this must be an exact name match against a WotC-curated
//: list, not a guessed pattern, so it's fetched verbatim rather than
//: hand-written: `curl 'https://api.scryfall.com/cards/search?q=is%3Agamechanger'`
//: (Scryfall keeps `is:gamechanger` synced to the official list). Pulled
//: 2026-07-08 — WotC revisits this list every few months (10 cards were
//: removed in the Oct 2025 update alone), so it will drift stale; re-run
//: that query to refresh. Names are lowercased and, for modal DFCs,
//: reduced to the front face (see `baseCardName`) to match however this
//: app's own card data spells them.
const GAME_CHANGERS = new Set([
  'ad nauseam',
  'ancient tomb',
  'aura shards',
  'biorhythm',
  "bolas's citadel",
  'braids, cabal minion',
  'chrome mox',
  'coalition victory',
  'consecrated sphinx',
  'crop rotation',
  'cyclonic rift',
  'demonic tutor',
  'drannith magistrate',
  'enlightened tutor',
  'farewell',
  'field of the dead',
  'fierce guardianship',
  'force of will',
  "gaea's cradle",
  'gamble',
  'gifts ungiven',
  'glacial chasm',
  'grand arbiter augustin iv',
  'grim monolith',
  'humility',
  'imperial seal',
  'intuition',
  "jeska's will",
  "lion's eye diamond",
  'mana vault',
  "mishra's workshop",
  'mox diamond',
  'mystical tutor',
  'narset, parter of veils',
  'natural order',
  'necropotence',
  'notion thief',
  'opposition agent',
  'orcish bowmasters',
  'panoptic mirror',
  'rhystic study',
  'seedborn muse',
  "serra's sanctum",
  'smothering tithe',
  'survival of the fittest',
  "teferi's protection",
  'tergrid, god of fright',
  "thassa's oracle",
  'the one ring',
  'the tabernacle at pendrell vale',
  'underworld breach',
  'vampiric tutor',
  'worldly tutor',
]);

//: Scryfall spells modal-DFC names as "Front // Back" — a deck entry
//: normally only names the front face, so this drops the back face
//: before comparing against `GAME_CHANGERS` (a set of front-face names).
function baseCardName(name) {
  return (name || '')
    .split(' // ')[0]
    .trim()
    .toLowerCase();
}

/** On WotC's official Game Changers list (0 allowed in Bracket 1–2, ≤3 in Bracket 3, unlimited in 4–5). */
export function isGameChanger(card) {
  return GAME_CHANGERS.has(baseCardName(card.name));
}

//: WotC's own named examples for "denies everyone's lands" effects whose
//: text doesn't reduce to a clean regex (Blood Moon: "Nonbasic lands are
//: Mountains", Winter Orb: "players can't untap more than one land …") —
//: supplements, doesn't replace, `MASS_LAND_DENIAL_RE` below.
const MASS_LAND_DENIAL_NAMES = new Set([
  'armageddon',
  'ruination',
  'sunder',
  'winter orb',
  'blood moon',
  'catastrophe',
  'global ruin',
  'ravages of war',
  'jokulhaups',
  'static orb',
  'back to basics',
  'stasis',
]);

//: The regex half of WotC's definition: "destroy, exile, and bounce
//: other lands ... for four or more lands per player without replacing
//: them." Deliberately doesn't try to count "four or more" — a symmetric
//: "destroy all lands"/"each player sacrifices ... lands" effect already
//: implies that in a multiplayer Commander pod.
const MASS_LAND_DENIAL_RE =
  /\b(destroy|exile)[^.]{0,20}\ball lands\b|\beach player (sacrifices|returns)[^.]{0,30}\blands?\b|\breturn all lands\b|\bcan't untap more than (a|one) land\b/i;

/** A Mass Land Denial effect (WotC: not intended below Bracket 4). */
export function isMassLandDenial(card) {
  return (
    !card.is_land &&
    (MASS_LAND_DENIAL_NAMES.has(baseCardName(card.name)) || MASS_LAND_DENIAL_RE.test(oracleText(card)))
  );
}

//: WotC doesn't restrict a single copy ("acceptable for splashy
//: moments") — only "chained in succession or looped," which isn't
//: determinable from a decklist alone. This just counts raw occurrences
//: as a coarse proxy a human still has to judge.
const EXTRA_TURN_RE = /\btakes? an extra turn\b/i;

/** Grants (some player) an extra turn. */
export function isExtraTurn(card) {
  return EXTRA_TURN_RE.test(oracleText(card));
}

/**
 * A plain-language summary of what the three checkable bracket signals
 * imply, given their raw counts — a lower bound, not a verdict: absence
 * of a signal never rules brackets 1–3 *in*, since bracket 1 vs. 2 vs. 3
 * is about deck tuning/intent, not anything checkable from a card list.
 * @returns {{minimumBracket: number|null, reasons: string[]}}
 */
export function suggestBracket(gameChangerCount, massLandDenialCount, extraTurnCount) {
  const reasons = [];
  let minimumBracket = null;

  if (gameChangerCount > 3) {
    minimumBracket = 4;
    reasons.push(t('da.bracket.gcOver3', { count: gameChangerCount }));
  } else if (gameChangerCount >= 1) {
    minimumBracket = 3;
    reasons.push(t('da.bracket.gcAny', { count: gameChangerCount }));
  }

  if (massLandDenialCount >= 1) {
    minimumBracket = 4;
    reasons.push(t('da.bracket.mld', { count: massLandDenialCount }));
  }

  if (extraTurnCount >= 2) {
    reasons.push(t('da.bracket.extraTurns', { count: extraTurnCount }));
  }

  return { minimumBracket, reasons };
}

const COLORS = ['W', 'U', 'B', 'R', 'G'];

const zeroByColor = () => ({ W: 0, U: 0, B: 0, R: 0, G: 0 });

/** log-space binomial coefficient (numerically safe for N up to a few hundred). */
function logChoose(n, k) {
  if (k < 0 || k > n) return -Infinity;
  let sum = 0;
  for (let i = 1; i <= k; i++) sum += Math.log(n - k + i) - Math.log(i);
  return sum;
}

/** P(exactly `k` successes) drawing `n` from a size-`N` population with `K` successes in it. */
function hypergeometricPmf(N, K, n, k) {
  if (N <= 0 || k < 0 || k > n) return 0;
  if (k > K || n - k > N - K) return 0;
  return Math.exp(logChoose(K, k) + logChoose(N - K, n - k) - logChoose(N, n));
}

/**
 * Turn-by-turn expected lands drawn (turn 1 = the opening 7-card hand, "on
 * the play" — no turn-1 draw; turn N>1 adds one natural draw), as a running
 * expectation over a shrinking population (the exact hypergeometric mean
 * at every step, so it matches the closed-form `n*K/N` exactly when
 * `fetchCount` is 0).
 *
 * When `fetchCount` > 0, each expected fraction of a fetchland drawn also
 * pulls one additional expected land out of the library immediately (a
 * fetch is assumed to always find a target) — modeling deck-thinning's
 * effect on *later* draws. This is an expectation-propagation
 * approximation (not a full distribution/simulation): it tracks the mean
 * remaining land density turn over turn rather than every possible draw
 * sequence, so it slightly understates variance but keeps the mean
 * correct by construction.
 */
export function expectedLandsOverTime(librarySize, landCount, fetchCount, maxTurn = 8) {
  let remainingLibrary = librarySize;
  let remainingLands = landCount;
  let remainingFetches = fetchCount;
  let acquired = 0;
  const turns = [];

  for (let turn = 1; turn <= maxTurn; turn++) {
    const draws = turn === 1 ? 7 : 1;
    for (let i = 0; i < draws && remainingLibrary > 0; i++) {
      const pLand = remainingLands / remainingLibrary;
      acquired += pLand;
      remainingLands -= pLand;
      remainingLibrary -= 1;

      if (remainingFetches > 0 && remainingLibrary > 0) {
        const pFetch = remainingFetches / (remainingLibrary + 1);
        remainingFetches = Math.max(0, remainingFetches - pFetch);
        const extraLand = Math.min(pFetch, remainingLands);
        acquired += extraLand;
        remainingLands = Math.max(0, remainingLands - extraLand);
        remainingLibrary = Math.max(0, remainingLibrary - extraLand);
      }
    }
    turns.push({ turn, expectedLands: acquired });
  }
  return turns;
}

/**
 * Exact expected land drops on the play, including fetches that can find a
 * non-fetch land. Unlike `min(turn, expected lands drawn)`, this averages
 * `min(actual lands in hand, turn)` over the hypergeometric draw outcomes.
 */
export function expectedLandDropsOverTime(librarySize, landCount, fetchCount, maxTurn = 8) {
  const initialState = [librarySize, landCount, fetchCount, 0, 0, 0];
  let states = new Map([[initialState.join(','), { state: initialState, probability: 1 }]]);
  const turns = [];

  function mergeState(target, state, probability) {
    const key = state.join(',');
    const existing = target.get(key);
    if (existing) existing.probability += probability;
    else target.set(key, { state, probability });
  }

  for (let turn = 1; turn <= maxTurn; turn++) {
    const draws = turn === 1 ? 7 : 1;
    for (let draw = 0; draw < draws; draw++) {
      const nextStates = new Map();
      for (const { state, probability } of states.values()) {
        const [remainingCards, remainingLands, remainingFetches, handLands, handFetches, landDrops] = state;
        if (remainingCards <= 0) {
          mergeState(nextStates, state, probability);
          continue;
        }

        if (remainingCards > remainingLands) {
          mergeState(
            nextStates,
            [remainingCards - 1, remainingLands, remainingFetches, handLands, handFetches, landDrops],
            (probability * (remainingCards - remainingLands)) / remainingCards
          );
        }
        if (remainingLands > remainingFetches) {
          mergeState(
            nextStates,
            [remainingCards - 1, remainingLands - 1, remainingFetches, handLands + 1, handFetches, landDrops],
            (probability * (remainingLands - remainingFetches)) / remainingCards
          );
        }
        if (remainingFetches > 0) {
          mergeState(
            nextStates,
            [remainingCards - 1, remainingLands - 1, remainingFetches - 1, handLands, handFetches + 1, landDrops],
            (probability * remainingFetches) / remainingCards
          );
        }
      }
      states = nextStates;
    }

    const afterLandDrop = new Map();
    for (const { state, probability } of states.values()) {
      const [remainingCards, remainingLands, remainingFetches, handLands, handFetches, landDrops] = state;
      if (handFetches > 0) {
        const canFetch = remainingLands > remainingFetches;
        mergeState(
          afterLandDrop,
          [
            remainingCards - (canFetch ? 1 : 0),
            remainingLands - (canFetch ? 1 : 0),
            remainingFetches,
            handLands,
            handFetches - 1,
            landDrops + 1,
          ],
          probability
        );
      } else if (handLands > 0) {
        mergeState(
          afterLandDrop,
          [remainingCards, remainingLands, remainingFetches, handLands - 1, handFetches, landDrops + 1],
          probability
        );
      } else {
        mergeState(afterLandDrop, state, probability);
      }
    }
    states = afterLandDrop;

    const expectedLandDrops = [...states.values()].reduce(
      (total, { state, probability }) => total + state[5] * probability,
      0
    );
    turns.push({ turn, expectedLandDrops });
  }
  return turns;
}

/**
 * Idealized "mana available if played on curve" for turns 1..maxTurn, as a
 * greedy turn-by-turn simulation rather than a flat "sum everything cheap
 * enough" formula — the latter allowed impossible turns (e.g. "casting"
 * a {1} rock, a {2} rock, and a {1} dork on turn 2 off of 2 mana). Each
 * turn: last turn's newly-cast accelerants come online, then as many
 * not-yet-cast accelerants as the best-case whole-mana budget allows are
 * cast, cheapest first. Mana rocks can be tapped immediately; other
 * accelerants start paying off next turn. One-shot
 * rituals are excluded from `accelerants` by the caller: their burst
 * doesn't compound turn over turn.
 *
 * This is the optimistic "maximum acceleration" curve: every accelerant
 * is available as soon as affordable and land drops are capped by the
 * deck's actual land count. It uses each land's recognized output, deducts
 * activation costs from mana-source output, and reserves one hand slot per
 * played land before counting accelerants. The realistic line instead
 * comes from shuffled hands and draws in `estimateExpectedManaCurve`.
 * @param {{name?: string, cmc: number, manaProduced: number, activationCost?: number, qty: number, kind?: string}[]} accelerants
 * @param {number[]} expectedLandsByTurn Expected land drops, one entry per
 *   turn 1..maxTurn (for example, `expectedLandDropsOverTime`).
 * @param {number} [maxTurn]
 * @param {{name?: string, qty: number, manaProduced: number, activationCost?: number, minimumLands?: number}[]|null} [landSources]
 */
export function simulateManaCurve(accelerants, expectedLandsByTurn, maxTurn = 8, landSources = null) {
  const pool = [];
  for (const a of accelerants) {
    for (let i = 0; i < a.qty; i++) {
      pool.push({
        name: a.name,
        cmc: a.cmc,
        manaProduced: a.manaProduced,
        activationCost: a.activationCost || 0,
        kind: a.kind,
      });
    }
  }
  pool.sort((a, b) => {
    const costOrder = a.cmc - b.cmc;
    const rockPriority = Number(b.kind === 'manaRock') - Number(a.kind === 'manaRock');
    return costOrder || rockPriority ||
      Math.max(0, b.manaProduced - b.activationCost) - Math.max(0, a.manaProduced - a.activationCost);
  });
  const availableLandSources = landSources
    .flatMap((source) =>
      Array.from(
        { length: source.qty },
        () => ({
          netProduction: Math.max(0, source.manaProduced - (source.activationCost || 0)),
          minimumLands: source.minimumLands || 0,
        })
      )
    );
  const deckLandCount = landSources?.reduce((total, source) => total + source.qty, 0) ?? 0;

  const turns = [];
  let onlineBonus = 0; // extra mana already paying off, from accelerants cast in strictly earlier turns
  let pendingBonus = 0; // accelerants cast THIS turn — come online next turn
  let idx = 0;

  for (let turn = 1; turn <= maxTurn; turn++) {
    onlineBonus += pendingBonus;
    pendingBonus = 0;
    const landDrops = landSources
      ? Math.min(turn, deckLandCount)
      : Math.min(turn, Math.ceil(expectedLandsByTurn[turn - 1] ?? turn));
    const landMana = landSources
      ? availableLandSources
          .filter((source) => source.minimumLands <= landDrops)
          .sort((a, b) => b.netProduction - a.netProduction)
          .slice(0, landDrops)
          .reduce((total, source) => total + source.netProduction, 0)
      : landDrops;
    const available = landMana + onlineBonus;
    // 7 opening-hand cards, +1 draw per turn since (on the play) — the hard
    // physical cap on cards seen so far, so even the uncapped "maximum"
    // curve can't cast more accelerants than could possibly be in hand yet.
    const cardsSeen = 6 + turn;
    const drawnSoFar = Math.max(0, cardsSeen - landDrops);
    let spent = 0;
    let manaToSpend = Math.ceil(available);
    let producedThisTurn = 0;
    const rampCardsCast = [];
    // This is the best-case curve: fractional expected mana is rounded up
    // only for deciding whether a source can be cast, never in the displayed
    // mana value itself.
    while (idx < pool.length && idx < drawnSoFar && pool[idx].cmc <= manaToSpend) {
      spent += pool[idx].cmc;
      manaToSpend -= pool[idx].cmc;
      const netProduction = Math.max(0, pool[idx].manaProduced - pool[idx].activationCost);
      pendingBonus += netProduction;
      if (pool[idx].kind === 'manaRock') {
        manaToSpend += netProduction;
        producedThisTurn += netProduction;
      }
      if (pool[idx].name) rampCardsCast.push(pool[idx].name);
      idx++;
    }
    turns.push({
      turn,
      withoutRamp: landMana,
      withRamp: available + producedThisTurn,
      spentOnRamp: spent,
      rampCardsCast,
    });
  }
  return turns;
}

const EXPECTED_MANA_CURVE_TRIALS = 8192; // Stable sample size for a smooth, repeatable expected value.
const MANA_CURVE_OPENING_HAND_SIZE = 7;
const MANA_CURVE_HASH_OFFSET_BASIS = 2166136261;
const MANA_CURVE_HASH_PRIME = 16777619;
const MANA_CURVE_RNG_LEFT_SHIFT_A = 13;
const MANA_CURVE_RNG_RIGHT_SHIFT = 17;
const MANA_CURVE_RNG_LEFT_SHIFT_B = 5;
const MANA_CURVE_UINT32_RANGE = 2 ** 32;

function seededRandom(seed) {
  let state = seed || MANA_CURVE_HASH_OFFSET_BASIS;
  return () => {
    state ^= state << MANA_CURVE_RNG_LEFT_SHIFT_A;
    state ^= state >>> MANA_CURVE_RNG_RIGHT_SHIFT;
    state ^= state << MANA_CURVE_RNG_LEFT_SHIFT_B;
    return (state >>> 0) / MANA_CURVE_UINT32_RANGE;
  };
}

/**
 * Expected mana production from shuffled opening hands and draws. The
 * expected land count cannot be used as a casting threshold: an average of
 * 0.96 lands on turn one still means most hands can cast a one-mana dork.
 * Reproducible sampling preserves those discrete draw/cast outcomes. It
 * assumes one land drop per turn, that fetchlands find a remaining land,
 * that mana rocks can be tapped immediately, and that creatures wait a turn.
 * @param {{name?: string, cmc: number, manaProduced: number, qty: number, kind?: string}[]} accelerants
 * @param {number} librarySize
 * @param {number} landCount
 * @param {number} fetchCount
 * @param {number} [maxTurn]
 */
export function estimateExpectedManaCurve(accelerants, librarySize, landCount, fetchCount, maxTurn = 8) {
  const rampCards = accelerants.flatMap((accelerant) =>
    Array.from({ length: accelerant.qty }, () => ({
      type: 'ramp',
      name: accelerant.name,
      cmc: accelerant.cmc,
      manaProduced: accelerant.manaProduced,
      activationCost: accelerant.activationCost || 0,
      kind: accelerant.kind,
    }))
  );
  const fetchLands = Math.min(fetchCount, landCount);
  const deck = [
    ...Array.from({ length: Math.max(0, landCount - fetchLands) }, () => ({ type: 'land' })),
    ...Array.from({ length: fetchLands }, () => ({ type: 'fetch' })),
    ...rampCards,
  ];
  while (deck.length < librarySize) deck.push({ type: 'other' });

  const stableInputs = [
    librarySize,
    landCount,
    fetchCount,
    ...accelerants
      .map(({ name, cmc, manaProduced, qty, kind }) => `${name}:${cmc}:${manaProduced}:${qty}:${kind}`)
      .sort(),
  ].join('|');
  let seed = MANA_CURVE_HASH_OFFSET_BASIS;
  for (let i = 0; i < stableInputs.length; i++) {
    seed = Math.imul(seed ^ stableInputs.charCodeAt(i), MANA_CURVE_HASH_PRIME);
  }
  const random = seededRandom(seed >>> 0);
  const totals = Array(maxTurn).fill(0);
  const sampledLandTotals = Array(maxTurn).fill(0);

  for (let trial = 0; trial < EXPECTED_MANA_CURVE_TRIALS; trial++) {
    const shuffled = [...deck];
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }

    const hand = shuffled.slice(0, MANA_CURVE_OPENING_HAND_SIZE);
    let nextCard = MANA_CURVE_OPENING_HAND_SIZE;
    let playedLands = 0;
    let onlineBonus = 0;
    let pendingBonus = 0;

    for (let turn = 1; turn <= maxTurn; turn++) {
      if (turn > 1 && nextCard < shuffled.length) hand.push(shuffled[nextCard++]);
      onlineBonus += pendingBonus;
      pendingBonus = 0;

      const landIndex = hand.findIndex((card) => card.type === 'fetch');
      const basicLandIndex = hand.findIndex((card) => card.type === 'land');
      const playedIndex = landIndex >= 0 ? landIndex : basicLandIndex;
      if (playedIndex >= 0) {
        const playedLand = hand.splice(playedIndex, 1)[0];
        playedLands++;
        if (playedLand.type === 'fetch') {
          const targetIndex = shuffled.findIndex(
            (card, index) => index >= nextCard && card.type === 'land'
          );
          if (targetIndex >= 0) shuffled.splice(targetIndex, 1);
        }
      }

      let manaToSpend = playedLands + onlineBonus;
      let producedThisTurn = 0;
      hand.sort((a, b) => {
        const costA = a.type === 'ramp' ? a.cmc : Infinity;
        const costB = b.type === 'ramp' ? b.cmc : Infinity;
        if (costA !== costB) return costA - costB;
        if (costA === Infinity) return 0;
        const rockPriority = Number(b.kind === 'manaRock') - Number(a.kind === 'manaRock');
        return rockPriority || Math.max(0, b.manaProduced - (b.activationCost || 0)) -
          Math.max(0, a.manaProduced - (a.activationCost || 0));
      });
      for (let i = 0; i < hand.length;) {
        const card = hand[i];
        if (card.type !== 'ramp' || manaToSpend < card.cmc) {
          i++;
          continue;
        }
        hand.splice(i, 1);
        manaToSpend -= card.cmc;
        const netProduction = Math.max(0, card.manaProduced - card.activationCost);
        pendingBonus += netProduction;
        if (card.kind === 'manaRock') {
          manaToSpend += netProduction;
          producedThisTurn += netProduction;
        }
      }
      totals[turn - 1] += playedLands + onlineBonus + producedThisTurn;
      sampledLandTotals[turn - 1] += playedLands;
    }
  }

  const expectedLandDrops = expectedLandDropsOverTime(librarySize, landCount, fetchCount, maxTurn);
  return totals.map((total, index) => ({
    turn: index + 1,
    withRamp:
      expectedLandDrops[index].expectedLandDrops +
      (total - sampledLandTotals[index]) / EXPECTED_MANA_CURVE_TRIALS,
  }));
}

/**
 * Estimate the first turn by which every combo card can be cast using the
 * per-turn mana curve. Unspent mana does not carry between turns; combo
 * pieces can be cast on separate turns and remain available for the combo.
 * This assumes all pieces are available to cast and is not a game simulation.
 * @param {{name: string, cost: number}[]} comboCards Required combo card copies.
 * @param {{turn: number, withRampMax: number, rampSpentMax?: number, rampCardsCastMax?: string[]}[]} manaCurve
 * @returns {number|null}
 */
export function estimateComboCastTurn(comboCards, manaCurve) {
  if (!comboCards.length || comboCards.some(({ cost }) => !Number.isFinite(cost) || cost < 0)) {
    return null;
  }

  const remainingCards = comboCards.map((card) => ({ ...card }));
  let latestPieceCastTurn = 0;
  for (const point of manaCurve) {
    for (const rampName of point.rampCardsCastMax || []) {
      const name = rampName.trim().toLowerCase();
      const comboIndex = remainingCards.findIndex(
        (card) => card.name.trim().toLowerCase() === name
      );
      if (comboIndex >= 0) {
        remainingCards.splice(comboIndex, 1);
        latestPieceCastTurn = point.turn;
      }
    }

    const rampSpent = point.rampSpentMax ?? 0;
    if (!Number.isFinite(point.withRampMax) || !Number.isFinite(rampSpent)) continue;
    // The maximum-ramp curve already commits this mana to accelerants; do not
    // spend the same mana again on combo pieces in that turn.
    let manaLeft = Math.max(0, point.withRampMax - rampSpent);
    remainingCards.sort((a, b) => b.cost - a.cost);
    for (let i = 0; i < remainingCards.length;) {
      if (remainingCards[i].cost <= manaLeft) {
        manaLeft -= remainingCards[i].cost;
        remainingCards.splice(i, 1);
        latestPieceCastTurn = point.turn;
      } else {
        i++;
      }
    }
    if (!remainingCards.length) return latestPieceCastTurn;
  }
  return null;
}

/**
 * Compute every static stat the "Deck analysieren" tab shows.
 * @param {{name: string, qty: number}[]} commanderEntries
 * @param {{name: string, qty: number}[]} libraryEntries The actual draw
 *   pile (mainboard) — deliberately excludes the commander(s), who don't
 *   dilute opening-hand/library odds (they start in the command zone).
 * @param {Map<string, {card: object}>} resolved Lowercased name → resolved
 *   entry, as returned by cardImages.js's resolveCardImages().
 */
export function analyzeDeck(commanderEntries, libraryEntries, resolved, comboData = null) {
  const cardFor = (name) => resolved.get(name.trim().toLowerCase())?.card ?? null;

  const unresolvedNames = [];
  /** @type {{entry: object, card: object}[]} */
  const library = [];
  for (const entry of libraryEntries) {
    const card = cardFor(entry.name);
    if (card) library.push({ entry, card });
    else unresolvedNames.push(entry.name);
  }
  const commanders = commanderEntries
    .map((entry) => ({ entry, card: cardFor(entry.name) }))
    .filter((c) => c.card);

  const librarySize = library.reduce((s, { entry }) => s + entry.qty, 0);

  // --- Mana curve (nonland) -------------------------------------------
  const curveBuckets = [0, 1, 2, 3, 4, 5, 6, '7+'].map((cmc) => ({ cmc, count: 0, names: [] }));
  const bucketFor = (cmc) => curveBuckets[Math.min(cmc, 7)];

  // --- Accelerant classification ---------------------------------------
  const manaRocks = [];
  const manaDorks = [];
  const manaLandAuras = []; // land-enchanting Auras: Wild Growth, Utopia Sprawl, …
  const landRampSpells = []; // land-tutors: Rampant Growth, Cultivate, …
  const rituals = []; // one-shot bursts: Dark Ritual, Jeska's Will, …
  const treasureGenerators = []; // Storm-Kiln Artist, Goldspan Dragon, …
  const recurringAccelerants = []; // rocks + dorks + landAuras + landRamp only (feeds simulateManaCurve)
  const manaProducingLands = [];

  // --- Land archetypes ---------------------------------------------------
  const landArchetypeCounts = Object.fromEntries(LAND_ARCHETYPES.map((a) => [a.key, { count: 0, names: [] }]));
  let fetchCount = 0;

  // --- Command Zone categories --------------------------------------------
  const commandZoneCounts = Object.fromEntries(COMMAND_ZONE_CATEGORIES.map((c) => [c.key, { count: 0, names: [] }]));
  const targetedDisruptionCounts = Object.fromEntries(
    TARGETED_DISRUPTION_KINDS.map((k) => [k.key, { count: 0, names: [] }])
  );
  const massDisruptionCounts = Object.fromEntries(MASS_DISRUPTION_KINDS.map((k) => [k.key, { count: 0, names: [] }]));
  const cardAdvantageCounts = Object.fromEntries(CARD_ADVANTAGE_KINDS.map((k) => [k.key, { count: 0, names: [] }]));

  // --- Commander Brackets --------------------------------------------------
  const gameChangers = []; // checked on lands too (Gaea's Cradle, Ancient Tomb, …)
  const massLandDenial = [];
  const extraTurnSpells = [];

  const tutors = [];
  let tutorCount = 0;

  // --- Type distribution / mana value / pips ----------------------------
  const typeCounts = Object.fromEntries(TYPE_BUCKETS.map((b) => [b.key, 0]));
  let nonlandCount = 0;
  let landCount = 0;
  let totalManaValue = 0;
  const cardPips = zeroByColor();
  const sourcePips = zeroByColor();

  for (const { entry, card } of library) {
    const qty = entry.qty;
    const cmc = card.converted_mana_cost || 0;

    for (const bucket of TYPE_BUCKETS) {
      if (bucket.test(card)) typeCounts[bucket.key] += qty;
    }

    // Checked before the is_land branch below: several Game Changers
    // (Gaea's Cradle, Ancient Tomb, Serra's Sanctum, Mishra's Workshop,
    // The Tabernacle at Pendrell Vale, Field of the Dead, Glacial Chasm)
    // are themselves lands.
    if (isGameChanger(card)) {
      gameChangers.push({ name: card.name, qty });
    }
    if (isMassLandDenial(card)) {
      massLandDenial.push({ name: card.name, qty });
    }
    if (isExtraTurn(card)) {
      extraTurnSpells.push({ name: card.name, qty });
    }
    if (isTutor(card)) {
      tutorCount += qty;
      tutors.push({ name: card.name, qty });
    }

    // A spell//land MDFC never satisfies card.is_land (front-face-only —
    // see isMdfcLand's comment), so it's counted into the Land-Archetypen
    // breakdown here, separately from the is_land branch below, and
    // WITHOUT `continue`: unlike a real land, it still occupies a spell
    // slot and keeps flowing through the mana-curve/ramp/functional-
    // category classification below as whatever its front face actually is.
    if (isMdfcLand(card)) {
      landArchetypeCounts.mdfc_land.count += qty;
      landArchetypeCounts.mdfc_land.names.push({ name: card.name, qty });
    }

    if (card.is_land) {
      landCount += qty;
      for (const color of COLORS) {
        if ((card.color_identity || []).includes(color)) sourcePips[color] += qty;
      }
      const archetype = landArchetype(card);
      landArchetypeCounts[archetype.key].count += qty;
      landArchetypeCounts[archetype.key].names.push({ name: card.name, qty });
      if (archetype.key === 'fetch') fetchCount += qty;
      const landMana = archetype.key === 'fetch' ? 1 : producesMana(card) ? manaProduced(card) : 0;
      manaProducingLands.push({
        name: card.name,
        qty,
        manaProduced: landMana,
        activationCost: archetype.key === 'fetch' ? 0 : manaAbilityActivationCost(card),
        minimumLands: archetype.key === 'fetch' ? 0 : manaAbilityMinimumLandCount(card),
      });
      commandZoneCounts.lands.count += qty;
      commandZoneCounts.lands.names.push({ name: card.name, qty });
      continue; // lands don't count toward the CMC curve/mana value
    }

    nonlandCount += qty;
    totalManaValue += cmc * qty;
    bucketFor(cmc).count += qty;
    bucketFor(cmc).names.push({ name: card.name, qty });

    const mc = card.mana_cost || {};
    for (const color of COLORS) cardPips[color] += (mc[color] || 0) * qty;

    let isRampCard = true;
    if (isTreasureGenerator(card)) {
      // Checked first: a burst/conditional resource (the token still has
      // to actually be created, often trigger-gated, then is consumed on
      // use), not a guaranteed recurring source — excluded from both the
      // mana-curve simulation and the "lands-equivalent" accelerant count.
      treasureGenerators.push({ name: card.name, qty, cmc });
    } else if (isManaRock(card)) {
      manaRocks.push({ name: card.name, qty, cmc });
      recurringAccelerants.push({
        name: card.name,
        cmc,
        manaProduced: manaProduced(card),
        activationCost: manaAbilityActivationCost(card),
        qty,
        kind: 'manaRock',
      });
      for (const color of COLORS) {
        if ((card.color_identity || []).includes(color)) sourcePips[color] += qty;
      }
    } else if (isManaDork(card)) {
      manaDorks.push({ name: card.name, qty, cmc });
      recurringAccelerants.push({
        name: card.name,
        cmc,
        manaProduced: manaProduced(card),
        activationCost: manaAbilityActivationCost(card),
        qty,
        kind: 'manaDork',
      });
      for (const color of COLORS) {
        if ((card.color_identity || []).includes(color)) sourcePips[color] += qty;
      }
    } else if (isManaLandAura(card)) {
      manaLandAuras.push({ name: card.name, qty, cmc });
      recurringAccelerants.push({
        name: card.name,
        cmc,
        manaProduced: manaProduced(card),
        activationCost: manaAbilityActivationCost(card),
        qty,
        kind: 'manaLandAura',
      });
      for (const color of COLORS) {
        if ((card.color_identity || []).includes(color)) sourcePips[color] += qty;
      }
    } else if (isOneShotManaSource(card)) {
      // A self-sacrifice (Lotus Petal) or hand-exile (Elvish Spirit Guide)
      // mana ability — consumed on the spot, so it's a ritual burst
      // regardless of the card being a creature/artifact rather than an
      // instant/sorcery (rampSpellKind below only looks at non-creatures).
      rituals.push({ name: card.name, qty, cmc });
    } else {
      const kind = rampSpellKind(card);
      if (kind === 'landFetch') {
        landRampSpells.push({ name: card.name, qty, cmc });
        recurringAccelerants.push({ name: card.name, cmc, manaProduced: 1, qty, kind: 'landRamp' });
      } else if (kind === 'ritual') {
        rituals.push({ name: card.name, qty, cmc });
      } else {
        isRampCard = false;
      }
    }

    const czCategory = commandZoneCategory(card, isRampCard);
    commandZoneCounts[czCategory.key].count += qty;
    commandZoneCounts[czCategory.key].names.push({ name: card.name, qty });
    if (czCategory.key === 'targeted_disruption') {
      targetedDisruptionCounts[czCategory.subKey].count += qty;
      targetedDisruptionCounts[czCategory.subKey].names.push({ name: card.name, qty });
    } else if (czCategory.key === 'mass_disruption') {
      massDisruptionCounts[czCategory.subKey].count += qty;
      massDisruptionCounts[czCategory.subKey].names.push({ name: card.name, qty });
    } else if (czCategory.key === 'card_advantage') {
      cardAdvantageCounts[czCategory.subKey].count += qty;
      cardAdvantageCounts[czCategory.subKey].names.push({ name: card.name, qty });
    }
  }

  // The commander(s) count toward Game Changers too (several — Grand
  // Arbiter Augustin IV, Tergrid, God of Fright, … — are commonly played
  // as one) but not Mass Land Denial/Extra Turns, which are never
  // sensible on a legendary creature/planeswalker commander.
  for (const { entry, card } of commanders) {
    if (isGameChanger(card)) gameChangers.push({ name: card.name, qty: entry.qty });
  }
  const bracketSuggestion = suggestBracket(
    gameChangers.reduce((s, c) => s + c.qty, 0),
    massLandDenial.reduce((s, c) => s + c.qty, 0),
    extraTurnSpells.reduce((s, c) => s + c.qty, 0)
  );

  // "Lands-equivalent" acceleration for the opening-hand stat: rocks,
  // dorks, land-enchanting Auras and land-tutors behave like an extra
  // land draw. Rituals (a one-shot burst spent on a single bigger turn)
  // and Treasure generators (conditional/trigger-gated, and consumed on
  // use) don't, so they're shown separately below rather than folded into
  // this count.
  const accelerantCount =
    manaRocks.reduce((s, a) => s + a.qty, 0) +
    manaDorks.reduce((s, a) => s + a.qty, 0) +
    manaLandAuras.reduce((s, a) => s + a.qty, 0) +
    landRampSpells.reduce((s, a) => s + a.qty, 0);

  // --- Opening hand (hypergeometric, drawn from the library only) ------
  const HAND_SIZE = 7;
  const landProbabilities = Array.from({ length: HAND_SIZE + 1 }, (_, k) => ({
    k,
    p: hypergeometricPmf(librarySize, landCount, HAND_SIZE, k),
  }));
  const expectedLands = librarySize ? (HAND_SIZE * landCount) / librarySize : 0;
  const expectedLandsPlusAccel = librarySize ? (HAND_SIZE * (landCount + accelerantCount)) / librarySize : 0;

  const landsOverTimeWithoutFetch = expectedLandsOverTime(librarySize, landCount, 0);
  const landsOverTimeWithFetch = expectedLandsOverTime(librarySize, landCount, fetchCount);
  const landsOverTime = landsOverTimeWithoutFetch.map((t, i) => ({
    turn: t.turn,
    withoutFetchBonus: t.expectedLands,
    withFetchBonus: landsOverTimeWithFetch[i].expectedLands,
  }));

  const landManaBasis = expectedLandDropsOverTime(librarySize, landCount, fetchCount).map(
    (t) => t.expectedLandDrops
  );
  const expectedManaCurveMax = simulateManaCurve(recurringAccelerants, landManaBasis, 8, manaProducingLands);
  const expectedManaCurveRealistic = estimateExpectedManaCurve(
    recurringAccelerants,
    librarySize,
    landCount,
    fetchCount
  );
  const expectedManaCurve = expectedManaCurveMax.map((p, i) => ({
    turn: p.turn,
    withoutRamp: p.withoutRamp,
    withRampMax: p.withRamp,
    rampSpentMax: p.spentOnRamp,
    rampCardsCastMax: p.rampCardsCast,
    withRampRealistic: expectedManaCurveRealistic[i].withRamp,
  }));

  const resolvedByCanonicalName = new Map(
    [...resolved.values()]
      .filter((entry) => entry?.card?.name)
      .map((entry) => [entry.card.name.trim().toLowerCase(), entry.card])
  );
  const comboAnalysis = (comboData?.combos || []).map((combo) => {
    const uses = Array.isArray(combo.uses) ? combo.uses : [];
    const cardCount = uses.reduce((sum, use) => sum + (Number(use.quantity) || 1), 0);
    const comboCards = [];
    let totalManaValue = 0;
    let manaValueKnown = true;
    for (const use of uses) {
      const card = resolvedByCanonicalName.get(String(use.name || '').trim().toLowerCase());
      const cmc = card?.converted_mana_cost;
      if (!Number.isFinite(cmc)) {
        manaValueKnown = false;
        break;
      }
      totalManaValue += cmc * (Number(use.quantity) || 1);
      for (let i = 0; i < (Number(use.quantity) || 1); i++) {
        comboCards.push({ name: String(use.name).trim(), cost: cmc });
      }
    }
    const hasUnverifiedRequirements = Boolean(combo.requirements?.length);
    const producesInfinite = (combo.produces || []).some((feature) =>
      /\binfinite\b/i.test(feature)
    );
    const earliestTurn = manaValueKnown ? estimateComboCastTurn(comboCards, expectedManaCurve) : null;
    const bracketImpact =
      hasUnverifiedRequirements || cardCount !== 2 || !producesInfinite || !manaValueKnown
        ? 'unverified'
        : earliestTurn !== null && earliestTurn <= 6
          ? 'bracket4'
          : 'bracket3';
    return {
      ...combo,
      cardCount,
      totalManaValue: manaValueKnown ? totalManaValue : null,
      earliestTurn,
      hasUnverifiedRequirements,
      producesInfinite,
      bracketImpact,
    };
  });
  const twoCardCombos = comboAnalysis.filter(
    (combo) =>
      combo.cardCount === 2 &&
      combo.producesInfinite &&
      !combo.hasUnverifiedRequirements &&
      Number.isFinite(combo.totalManaValue)
  );
  const earlyTwoCardCombos = twoCardCombos.filter((combo) => combo.bracketImpact === 'bracket4');
  let minimumBracket = bracketSuggestion.minimumBracket;
  if (twoCardCombos.length) minimumBracket = Math.max(minimumBracket || 0, 3);
  if (earlyTwoCardCombos.length) minimumBracket = Math.max(minimumBracket || 0, 4);
  const bracketReasons = [...bracketSuggestion.reasons];
  if (twoCardCombos.length) {
    bracketReasons.push(t('da.bracket.twoCardCombos', { count: twoCardCombos.length }));
  }
  if (earlyTwoCardCombos.length) {
    bracketReasons.push(
      t('da.bracket.earlyTwoCardCombos', { count: earlyTwoCardCombos.length })
    );
  }

  return {
    unresolvedNames,
    librarySize,
    tutorCount,
    commanders: commanders.map(({ entry, card }) => ({
      name: card.name,
      qty: entry.qty,
      cmc: card.converted_mana_cost || 0,
      colorIdentity: card.color_identity || [],
      typeLine: card.type_line,
    })),
    manaCurve: curveBuckets,
    expectedManaCurve,
    typeDistribution: TYPE_BUCKETS.map((b) => ({ key: b.key, label: b.label, count: typeCounts[b.key] })),
    landArchetypes: LAND_ARCHETYPES.map((a) => ({
      key: a.key,
      label: a.label,
      count: landArchetypeCounts[a.key].count,
      names: landArchetypeCounts[a.key].names,
    })).filter((a) => a.count > 0),
    manaValue: {
      total: totalManaValue,
      nonlandCount,
      landCount,
      averageWithLands: librarySize ? totalManaValue / librarySize : 0,
      averageWithoutLands: nonlandCount ? totalManaValue / nonlandCount : 0,
    },
    openingHand: {
      librarySize,
      landCount,
      fetchCount,
      accelerantCount,
      expectedLands,
      expectedLandsPlusAccel,
      landProbabilities,
      landsOverTime,
    },
    accelerants: { manaRocks, manaDorks, manaLandAuras, landRampSpells, rituals, treasureGenerators },
    colorPips: { cards: cardPips, sources: sourcePips },
    commandZone: {
      categories: COMMAND_ZONE_CATEGORIES.map((c) => ({
        key: c.key,
        label: c.label,
        count: commandZoneCounts[c.key].count,
        names: commandZoneCounts[c.key].names,
      })),
      targetedDisruption: TARGETED_DISRUPTION_KINDS.map((k) => ({
        key: k.key,
        label: k.label,
        count: targetedDisruptionCounts[k.key].count,
        names: targetedDisruptionCounts[k.key].names,
      })).filter((k) => k.count > 0),
      massDisruption: MASS_DISRUPTION_KINDS.map((k) => ({
        key: k.key,
        label: k.label,
        count: massDisruptionCounts[k.key].count,
        names: massDisruptionCounts[k.key].names,
      })).filter((k) => k.count > 0),
      cardAdvantage: CARD_ADVANTAGE_KINDS.map((k) => ({
        key: k.key,
        label: k.label,
        count: cardAdvantageCounts[k.key].count,
        names: cardAdvantageCounts[k.key].names,
      })).filter((k) => k.count > 0),
      tutors,
    },
    bracketAnalysis: {
      gameChangers,
      massLandDenial,
      extraTurnSpells,
      combos: comboAnalysis,
      comboDataLoaded: comboData !== null,
      comboTwoCardCount: twoCardCombos.length,
      comboEarlyTwoCardCount: earlyTwoCardCombos.length,
      comboUnknownCount: comboAnalysis.filter((combo) => combo.bracketImpact === 'unverified').length,
      minimumBracket,
      reasons: bracketReasons,
    },
  };
}
