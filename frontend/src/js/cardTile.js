// Shared "detailed card" tile renderer: image (shown in full, no crop) +
// name + type + mana cost (as emoji) + oracle text + keywords + set/rarity.
// Used by both the "Karten-Cache" tab (cachedCardsView.js) and the
// deck-import card lists' detail view (deckImportView.js) so the two
// don't duplicate the mana-cost-to-emoji logic.

import { cardImageUrl } from './api.js';
import { t } from './i18n.js';

// Colored mana symbols get a matching colored circle; {C} (the specific
// colorless-mana symbol, distinct from generic cost) gets a neutral one.
// Exported so other views (gameBoardView.js's mana pool / mana-potential
// readout) share this one WUBRGC glyph set instead of keeping their own,
// possibly-diverging copy.
export const MANA_SYMBOL_EMOJI = { W: '⚪', U: '🔵', B: '⚫', R: '🔴', G: '🟢', C: '🔘' };

// Keycap digit emojis, indexed by digit — used to spell out generic mana
// (e.g. 12 -> "1️⃣2️⃣") one character at a time, so any amount works without
// a lookup table per number.
const DIGIT_EMOJI = ['0️⃣', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣'];

function genericManaEmoji(amount) {
  return String(amount)
    .split('')
    .map((digit) => DIGIT_EMOJI[Number(digit)])
    .join('');
}

const MANA_TOKEN_RE = /\{([^}]+)\}/g;

// One `{...}` token (already stripped of braces) to its faithful display.
// Mirrors the backend's `ManaSymbol` kinds (mtg_analyzer/models/mana_cost.py):
// generic, {X}/{Y}/{Z}, plain color/colorless, hybrid ({W/U}), monocolored
// hybrid ({2/W}), and Phyrexian ({W/P}) — each rendered so the choice it
// offers stays visible instead of collapsing to a plain pip.
function renderManaToken(token) {
  const symbol = token.trim().toUpperCase();

  if (/^\d+$/.test(symbol)) return genericManaEmoji(Number(symbol));
  if (symbol === 'X' || symbol === 'Y' || symbol === 'Z') return symbol;
  if (MANA_SYMBOL_EMOJI[symbol]) return MANA_SYMBOL_EMOJI[symbol];

  if (symbol.includes('/')) {
    const parts = symbol.split('/');
    if (parts.includes('P')) {
      const color = parts.find((p) => p !== 'P' && MANA_SYMBOL_EMOJI[p]);
      if (color) return `(${MANA_SYMBOL_EMOJI[color]}/🩸)`; // pay the color, or 2 life
    }
    const generic = parts.find((p) => /^\d+$/.test(p));
    const hybridColor = parts.find((p) => MANA_SYMBOL_EMOJI[p]);
    if (generic && hybridColor) {
      return `(${genericManaEmoji(Number(generic))}/${MANA_SYMBOL_EMOJI[hybridColor]})`;
    }
    if (parts.every((p) => MANA_SYMBOL_EMOJI[p])) {
      return `(${parts.map((p) => MANA_SYMBOL_EMOJI[p]).join('/')})`;
    }
  }

  return symbol; // unknown symbol (snow {S}, ...): show the letter, not a guess
}

// Card.mana_cost (the legacy flattened form) only counts colored/colorless
// pips ({W}, {U}, ..., {C}) and drops generic amounts, hybrid/Phyrexian
// nuance entirely. `mana_cost_string` (the raw Scryfall string, e.g.
// "{2}{W}{U/B}{G/P}") is faithful and preferred; the pip-counting fallback
// below only fires for rows cached before that field existed (see backend's
// `ManaCost.from_card`) and can't recover the nuance it never stored.
export function renderManaCost(card) {
  if (card.mana_cost_string) {
    const tokens = card.mana_cost_string.match(MANA_TOKEN_RE) || [];
    return tokens.map((tok) => renderManaToken(tok.slice(1, -1))).join(' ');
  }

  const pips = card.mana_cost || {};
  const pipTotal = Object.values(pips).reduce((sum, count) => sum + count, 0);
  const generic = Math.max(0, (card.converted_mana_cost || 0) - pipTotal);

  const parts = [];
  if (generic > 0) parts.push(genericManaEmoji(generic));
  for (const symbol of ['C', 'W', 'U', 'B', 'R', 'G']) {
    const count = pips[symbol] || 0;
    if (count > 0) parts.push(MANA_SYMBOL_EMOJI[symbol].repeat(count));
  }
  return parts.join(' ');
}

/**
 * Oracle/reminder text with every `{...}` mana symbol (activation costs,
 * "Add {G}", etc.) swapped for the same emoji `renderManaCost` uses for the
 * cost line — everything else is escaped exactly like plain `escapeHtml`
 * would. Splitting on `MANA_TOKEN_RE` with a capture group keeps the
 * delimiters in the result, so the plain-text segments between symbols are
 * escaped individually rather than the icons getting escaped along with them.
 */
// One capture group only, deliberately not reusing `MANA_TOKEN_RE.source`
// wrapped in another `(...)` — that regex already has its own inner group
// (for the trimmed symbol name), and split() inserts *every* captured
// group's text into the result, so nesting a second group around it left
// each token's bare content duplicated right after its own emoji (e.g.
// "{0}" rendering as "0️⃣0").
const MANA_TOKEN_SPLIT_RE = /(\{[^}]+\})/g;
const MANA_TOKEN_WHOLE_RE = /^\{([^}]+)\}$/;

export function renderOracleText(text) {
  return String(text)
    .split(MANA_TOKEN_SPLIT_RE)
    .map((part) => {
      const m = MANA_TOKEN_WHOLE_RE.exec(part);
      return m ? renderManaToken(m[1]) : escapeHtml(part);
    })
    .join('');
}

/**
 * Scryfall's exact-name search redirects straight to the card's page
 * when the name is unambiguous (verified by hand: a 303 to
 * /card/<set>/<number>/<slug>), so this needs no card id/set from the
 * backend — just the name already on every resolved card dict.
 * @param {string} cardName
 */
export function scryfallUrl(cardName) {
  return `https://scryfall.com/search?q=${encodeURIComponent(`!"${cardName}"`)}`;
}

/**
 * Plain (non-exact) Scryfall search — unlike `scryfallUrl`'s `!"..."`
 * exact match, this surfaces near-matches, so a not-found name like
 * "Tin Street Kingpin" (missing the "Krenko, " the real name starts
 * with) still finds the card it probably meant.
 * @param {string} cardName
 */
export function scryfallSearchUrl(cardName) {
  return `https://scryfall.com/search?q=${encodeURIComponent(cardName)}`;
}

const ILLEGAL_REASON_LABELS = {
  banned: 'cardTile.illegal.banned',
  colorIdentity: 'cardTile.illegal.colorIdentity',
};

/**
 * `card.coverage` (only present on `GET /api/cards` — the Karten-Cache
 * listing, see `api/cards.py`'s `_coverage_for`) tells whether the rules
 * engine actually binds this card's abilities: a hand-authored
 * `ability_catalogue` entry or a fully `MODELED` oracle-parser verdict, vs.
 * a card where only its keywords are recognized and everything else (its
 * spell/trigger/static effects) is inert. See CLAUDE.md's oracle-text
 * pipeline section and `parser/oracle/gate.py`.
 */
function renderCoverageBadge(coverage) {
  if (!coverage) return '';
  if (coverage.modeled) {
    const catalogue = coverage.source === 'catalogue';
    const title = catalogue
      ? t('cardTile.coverage.catalogueTitle')
      : t('cardTile.coverage.oracleTitle');
    return `<span class="card-tile-coverage card-tile-coverage-modeled" title="${escapeAttr(title)}">${catalogue ? '📖' : '✅'} ${catalogue ? t('cardTile.coverage.catalogued') : t('cardTile.coverage.modeled')}</span>`;
  }
  const unclaimed = coverage.unclaimed || [];
  const title = unclaimed.length
    ? t('cardTile.coverage.unmodeledTitleWithText', { text: unclaimed.join('\n') })
    : t('cardTile.coverage.unmodeledTitle');
  return `<span class="card-tile-coverage card-tile-coverage-unmodeled" title="${escapeAttr(title)}">${t('cardTile.coverage.unmodeled')}</span>`;
}

/** Footnote row pinned to the bottom of a tile: coverage badge (if any) + the
 * Scryfall link, always together so the tile's last line of text is a
 * consistent "meta" row regardless of how much oracle text/keywords sit above it. */
function renderTileFooter(coverageBadge, scryfallHref, scryfallTitle) {
  return `
    <div class="card-tile-footer">
      ${coverageBadge}
      <a
        class="card-tile-scryfall-link"
        href="${scryfallHref}"
        target="_blank"
        rel="noopener noreferrer"
        title="${scryfallTitle}"
        aria-label="${scryfallTitle}"
      >🔗</a>
    </div>`;
}

/**
 * @param {object} card A resolved card dict (Card.to_dict() shape).
 * @param {{qty?: number, illegalReason?: 'banned'|'colorIdentity'|null, favorite?: boolean}} [options]
 *   `qty`: optional quantity badge (deck-import context only).
 *   `illegalReason`: set when the deck's commander-legality check
 *   (POST /api/decks) flagged this exact card — banned, or outside the
 *   commander's color identity — so it can still be shown (this is a
 *   real, resolved card) with a "why" marker rather than removed.
 *   `favorite`: when passed (deck-import context only — omit to render no
 *   star at all, e.g. `cachedCardsView.js`'s read-only cache browser),
 *   renders a toggleable favorite star reflecting `Deck.favoriteCards`
 *   (`models/deck.py`). Toggling only updates this tile's own DOM (see the
 *   delegated handler at the bottom of this module) and dispatches a
 *   `card-tile-favorite-toggle` event — the host view listens for that to
 *   update its own tracked favorite set rather than this module owning any
 *   state itself.
 */
export function renderCardTile(card, { qty, illegalReason, favorite } = {}) {
  const manaCost = renderManaCost(card);
  const powerToughness = card.power != null && card.toughness != null ? `${card.power}/${card.toughness}` : '';
  const metaParts = [card.rarity, card.set_code ? card.set_code.toUpperCase() : ''].filter(Boolean);
  const qtyBadge = qty != null ? `<span class="card-tile-qty">${qty}×</span>` : '';
  const illegalLabel = illegalReason ? t(ILLEGAL_REASON_LABELS[illegalReason]) : '';

  // Double-faced cards (transform / modal DFC) carry a second image the
  // player can flip to; the button below toggles the <img> between the
  // two faces (see the delegated handler at the bottom of this module).
  const flipButton = card.has_back_face
    ? `<button type="button" class="card-tile-flip"
         data-front-src="${cardImageUrl(card.id, 'normal', 'front')}"
         data-back-src="${cardImageUrl(card.id, 'normal', 'back')}"
         title="${escapeAttr(t('cardTile.showBack'))}" aria-label="${escapeAttr(t('cardTile.showBack'))}">🔄</button>`
    : '';

  const favoriteButton =
    favorite !== undefined
      ? `<button type="button" class="card-tile-favorite${favorite ? ' is-favorite' : ''}"
           data-favorite-card="${escapeAttr(card.name)}" aria-pressed="${favorite}"
           title="${escapeAttr(t('cardTile.toggleFavorite'))}" aria-label="${escapeAttr(t('cardTile.toggleFavorite'))}">${favorite ? '★' : '☆'}</button>`
      : '';

  return `
    <div class="card-tile${illegalReason ? ' card-tile-illegal' : ''}">
      <div class="card-tile-image">
        ${qtyBadge}
        ${flipButton}
        ${favoriteButton}
        <img src="${cardImageUrl(card.id, 'normal')}" alt="${escapeHtml(card.name)}" loading="lazy" />
      </div>
      <div class="card-tile-info">
        <h4>${illegalLabel ? '❗ ' : ''}${escapeHtml(card.name)}</h4>
        ${illegalLabel ? `<p class="card-tile-illegal-reason">❗ ${escapeHtml(illegalLabel)}</p>` : ''}
        <p class="card-tile-type">${escapeHtml(card.type_line)}</p>
        ${manaCost ? `<p class="card-tile-cost">${manaCost}</p>` : ''}
        ${powerToughness ? `<p class="card-tile-pt">${escapeHtml(powerToughness)}</p>` : ''}
        ${card.oracle_text ? `<p class="card-tile-text">${renderOracleText(card.oracle_text)}</p>` : ''}
        ${card.keywords?.length ? `<p class="card-tile-keywords">${escapeHtml(card.keywords.join(', '))}</p>` : ''}
        ${metaParts.length ? `<p class="card-tile-meta">${escapeHtml(metaParts.join(' · '))}</p>` : ''}
        ${renderTileFooter(renderCoverageBadge(card.coverage), scryfallUrl(card.name), t('cardTile.viewOnScryfall'))}
      </div>
    </div>
  `;
}

/** Fallback tile for a card name with no resolved data yet (still loading / unknown). */
export function renderCardTilePlaceholder(name, { qty } = {}) {
  const qtyBadge = qty != null ? `<span class="card-tile-qty">${qty}×</span>` : '';
  return `
    <div class="card-tile card-tile-placeholder">
      <div class="card-tile-image">
        ${qtyBadge}
      </div>
      <div class="card-tile-info">
        <h4>${escapeHtml(name)}</h4>
        <p class="card-tile-type empty-state">${t('common.loading')}</p>
        ${renderTileFooter('', scryfallUrl(name), t('cardTile.viewOnScryfall'))}
      </div>
    </div>
  `;
}

/** Tile for a card name the backend confirmed no match for (typo, or a
 * card that genuinely doesn't exist under that exact name — see
 * docs/implementation-state/Done_Backend.md "Validator" on exact- vs. fuzzy-name matching). */
export function renderCardTileNotFound(name, { qty } = {}) {
  const qtyBadge = qty != null ? `<span class="card-tile-qty">${qty}×</span>` : '';
  return `
    <div class="card-tile card-tile-placeholder card-tile-not-found">
      <div class="card-tile-image">
        ${qtyBadge}
      </div>
      <div class="card-tile-info">
        <h4>🛑 ${escapeHtml(name)}</h4>
        <p class="card-tile-type not-found">${t('cardTile.notFound')}</p>
        ${renderTileFooter('', scryfallSearchUrl(name), t('cardTile.searchOnScryfall'))}
      </div>
    </div>
  `;
}

export function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

// The card tiles are rendered as HTML strings and injected via innerHTML,
// so there's no per-tile element to bind to. One delegated listener,
// registered once when this module loads, handles every flip button:
// it swaps the sibling <img>'s src between the front and back face URLs
// carried on the button's data-* attributes.
if (typeof document !== 'undefined') {
  document.addEventListener('click', (event) => {
    const button = event.target.closest?.('.card-tile-flip');
    if (!button) return;
    const img = button.parentElement?.querySelector('img');
    if (!img) return;
    const showingBack = button.classList.toggle('is-flipped');
    img.src = showingBack ? button.dataset.backSrc : button.dataset.frontSrc;
  });

  // Same delegated-listener shape as the flip button above: this only
  // flips the button's own DOM (class/glyph/aria-pressed) — the favorite
  // *set* itself is owned by whichever view rendered the tile
  // (deckImportView.js), which listens for this event to stay in sync
  // rather than cardTile.js holding any state of its own.
  document.addEventListener('click', (event) => {
    const button = event.target.closest?.('.card-tile-favorite');
    if (!button) return;
    const isFavorite = button.classList.toggle('is-favorite');
    button.setAttribute('aria-pressed', String(isFavorite));
    button.textContent = isFavorite ? '★' : '☆';
    button.dispatchEvent(
      new CustomEvent('card-tile-favorite-toggle', {
        bubbles: true,
        detail: { name: button.dataset.favoriteCard, favorite: isFavorite },
      })
    );
  });
}
