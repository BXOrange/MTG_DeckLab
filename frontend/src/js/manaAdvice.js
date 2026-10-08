// Deterministic empirical advice and exact draw probabilities, independent
// of any gameplay simulation. Classifications follow Karsten's 2022 article:
// https://www.peasant-magic.com/articles/magic-deckbuilding/how-many-lands-do-you-need-in-your-deck-an-updated-analysis

export function cheapCardKind(card) {
  if (card.is_land) return null;
  const text = (card.oracle_text || '').toLowerCase();
  const cycling = /\bcycling\s*\{[1wubrgc]\}(?!\s*\{)/i.test(text);
  if (cycling) return 'draw';
  if (card.converted_mana_cost > 2) return null;
  const drawPhrase = ['draw a card', 'draw two cards', 'draw three cards',
    'draws cards', 'draws two cards', 'draws three cards'].some((phrase) => text.includes(phrase));
  const excludedDraw = ['{4}', 'blood token', 'investigate'].some((phrase) => text.includes(phrase));
  const draw = drawPhrase && !excludedDraw
    && (!card.is_creature || (text.includes('when') && text.includes('enters')));
  const selection = !card.is_creature && ['look', 'library', 'put', 'your hand'].every((phrase) => text.includes(phrase))
    && !text.includes('pay ') && !text.includes('pays');
  if (draw || selection) return 'draw';
  const mana = text.includes('add ') && !text.includes('add its ability')
    && !text.includes('add a lore counter') && (!card.is_creature || !text.includes('dies'));
  const landSearch = text.includes('search') && text.includes('your library')
    && (text.includes('land') || text.includes('basic')) && !text.includes('sacrifice');
  const aura = text.includes('enchanted land is tapped') && text.includes('adds an additional');
  const vial = text.includes('put a creature card with') && text.includes('from your hand onto the battlefield');
  return mana || landSearch || aura || vial ? 'ramp' : null;
}

export function isEarlyRamp(card) {
  if (card.is_land || card.converted_mana_cost > 2 || card.layout === 'modal_dfc') return false;
  const text = (card.oracle_text || '').replace(/\([^)]*\)/g, ' ');
  // A draw-availability category, not proof that mana costs/conditions can
  // be paid. Keep conditional triggers, rituals and search-to-hand separate.
  const ability = text.match(/([^\.\n]*):\s*Add\s+([^\.\n]+)/i);
  const permanent = card.is_creature || /\b(artifact|enchantment)\b/i.test(card.type_line || '');
  const repeatable = permanent && ability && !/\b(sacrifice|discard|exile|remove|pay)\b/i.test(ability[1])
    && !/\bX\b/i.test(ability[2])
    && !/\b(if|for each|equal to|activate(?: this ability)? only|spend this mana)\b/i.test(text);
  const aura = /\benchant (land|forest)\b/i.test(text) && /adds? an additional/i.test(text);
  const landSearch = /search your library for[^.]*\b(land|basic|plains|island|swamp|mountain|forest)\b[^.]*\bonto the battlefield\b/i.test(text)
    && !/\b(if|unless|for each|equal to)\b/i.test(text);
  return Boolean(repeatable || aura || landSearch);
}

function logChoose(n, k) {
  if (k < 0 || k > n) return -Infinity;
  let sum = 0;
  for (let i = 1; i <= Math.min(k, n - k); i++) sum += Math.log(n - i + 1) - Math.log(i);
  return sum;
}

/** Exact probability of >= minimum successes among draws, without replacement. */
export function drawProbability(size, successes, draws, minimum = 1) {
  if (!Number.isInteger(size) || size <= 0 || successes < 0 || successes > size || draws < 0) return 0;
  draws = Math.min(size, draws);
  let probability = 0;
  for (let k = Math.max(0, minimum); k <= Math.min(draws, successes); k++) {
    probability += Math.exp(logChoose(successes, k) + logChoose(size - successes, draws - k) - logChoose(size, draws));
  }
  return Math.min(1, Math.max(0, probability));
}

/** Joint event for disjoint land/ramp/other categories; no independence assumption. */
export function jointDrawProbability(size, lands, ramp, draws, minLands = 2, minRamp = 1) {
  if (size <= 0 || lands < 0 || ramp < 0 || lands + ramp > size) return 0;
  draws = Math.min(size, draws);
  let probability = 0;
  for (let l = minLands; l <= Math.min(lands, draws); l++) {
    for (let r = minRamp; r <= Math.min(ramp, draws - l); r++) {
      probability += Math.exp(logChoose(lands, l) + logChoose(ramp, r)
        + logChoose(size - lands - ramp, draws - l - r) - logChoose(size, draws));
    }
  }
  return Math.min(1, Math.max(0, probability));
}

export function requiredRampCount(size, target, draws = 9, lands = 0) {
  for (let ramp = 0; ramp <= size - lands; ramp++) {
    if (drawProbability(size, ramp, draws) >= target) return ramp;
  }
  return null;
}

export function analyzeManaAdvice(parsed, resolved) {
  let size = 0;
  let lands = 0;
  let nonlands = 0;
  let totalManaValue = 0;
  let mdfcCredit = 0;
  let unknownMdfcs = 0;
  const drawCards = [];
  const rampCards = [];
  const earlyRampCards = [];
  for (const entry of parsed.mainDeck) {
    const card = resolved.get(entry.name.trim().toLowerCase())?.card;
    if (!card || (!Number.isFinite(card.converted_mana_cost) && !card.is_land)) return { error: true };
    const quantity = entry.qty;
    size += quantity;
    if (card.is_land) { lands += quantity; continue; }
    nonlands += quantity;
    totalManaValue += card.converted_mana_cost * quantity;
    if (card.layout === 'modal_dfc' && /\bland\b/i.test(card.back_type_line || '')) {
      if (!card.rarity) unknownMdfcs += quantity;
      else mdfcCredit += quantity * (card.rarity === 'mythic' ? 0.74 : 0.38);
    }
    const kind = cheapCardKind(card);
    if (kind === 'draw') drawCards.push({ name: card.name, quantity });
    if (kind === 'ramp') rampCards.push({ name: card.name, quantity });
    if (isEarlyRamp(card)) earlyRampCards.push({ name: card.name, quantity });
  }
  if (!size || !nonlands || !parsed.commanders.length
      || parsed.commanders.some((entry) => !resolved.get(entry.name.trim().toLowerCase())?.card)) return { error: true };
  const count = (cards) => cards.reduce((sum, card) => sum + card.quantity, 0);
  const cheapDraw = count(drawCards);
  const cheapRamp = count(rampCards);
  const earlyRamp = count(earlyRampCards);
  const averageManaValue = totalManaValue / nonlands;
  const effectiveTarget = 31.42 + 3.13 * averageManaValue - 0.28 * (cheapDraw + cheapRamp);
  return { size, lands, averageManaValue, cheapDraw, cheapRamp, earlyRamp,
    drawCards, rampCards, earlyRampCards, mdfcCredit, unknownMdfcs,
    effectiveTarget, landTarget: unknownMdfcs ? null : Math.max(0, Math.round(effectiveTarget - mdfcCredit)),
    probabilities: [
      { turn: 0, draws: Math.min(size, 7), minLands: 2 },
      { turn: 2, draws: Math.min(size, 9), minLands: 2 },
      { turn: 3, draws: Math.min(size, 10), minLands: 3 },
    ].map((row) => ({ ...row, rampChance: drawProbability(size, earlyRamp, row.draws),
      jointChance: jointDrawProbability(size, lands, earlyRamp, row.draws, row.minLands) })),
  };
}
