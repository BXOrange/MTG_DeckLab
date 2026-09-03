// Shared setup/board-adjacent markup helpers for the play modes
// (Goldfisch / Solo-gegen-Bots / Multiplayer). Mostly pure markup functions —
// each of these used to be copy-pasted into `goldfishView.js` *and*
// `multiplayerView.js`; `soloView.js` is the third caller, so they live
// here once instead of being triplicated. `loadUnmodeledDeckIds` is the one
// exception (it makes network calls), kept here so the "⚠️" deck-picker
// marker stays a single implementation across all three modes.

import { getDeckCoverage } from './api.js';
import { t } from './i18n.js';

/** HTML-escape arbitrary text for use as element content. */
export function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

/** HTML-escape text for use inside a double-quoted attribute. */
export function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, '&quot;');
}

/**
 * A copy of `decks` with the player's favorites (Profil tab) sorted to the
 * front. `Array.prototype.sort` is stable, so ties keep the caller's
 * original order rather than being re-sorted by name.
 * @param {Array<{id: string}>} decks
 * @param {Set<string>|string[]} favoriteIds
 */
export function sortDecksFavoritesFirst(decks, favoriteIds) {
  const fav = favoriteIds instanceof Set ? favoriteIds : new Set(favoriteIds || []);
  return [...(decks || [])].sort(
    (a, b) => (fav.has(b.id) ? 1 : 0) - (fav.has(a.id) ? 1 : 0),
  );
}

/**
 * `<option>` list for a saved-deck `<select>`, favorites first, with the
 * loading / network-error / empty states every deck picker needs.
 * A deck whose id is in `unmodeledDeckIds` is prefixed with "⚠️" — it holds
 * cards the rules engine doesn't model yet (a goldfishing-readiness hint, not
 * a legality gate). Populate that set with `loadUnmodeledDeckIds` below.
 * @param {{savedDecks: Array|null, selectedId?: string,
 *   favoriteDeckIds?: Set<string>|string[], unmodeledDeckIds?: Set<string>|string[],
 *   decksLoading?: boolean, decksLoadError?: boolean, placeholder?: string,
 *   errorText?: string}} opts
 */
export function deckSelectOptionsHtml({
  savedDecks,
  selectedId = '',
  favoriteDeckIds = new Set(),
  unmodeledDeckIds = new Set(),
  decksLoading = false,
  decksLoadError = false,
  placeholder = t('setup.pickDeck'),
  errorText = t('setup.serverUnreachableDash'),
} = {}) {
  if (savedDecks == null || (decksLoading && savedDecks == null)) {
    return `<option>${t('setup.loadingOption')}</option>`;
  }
  if (decksLoadError) return `<option value="">${escapeHtml(errorText)}</option>`;
  if (!savedDecks.length) return `<option value="">${t('setup.noDecksDash')}</option>`;
  const fav = favoriteDeckIds instanceof Set ? favoriteDeckIds : new Set(favoriteDeckIds || []);
  const unmodeled =
    unmodeledDeckIds instanceof Set ? unmodeledDeckIds : new Set(unmodeledDeckIds || []);
  const options = [`<option value="">${escapeHtml(placeholder)}</option>`];
  for (const d of sortDecksFavoritesFirst(savedDecks, fav)) {
    const name = (d.name || '').trim() || t('common.unnamedDeck');
    const marker = unmodeled.has(d.id) ? '⚠️ ' : '';
    const label = fav.has(d.id) ? `★ ${marker}${name}` : `${marker}${name}`;
    const title = unmodeled.has(d.id)
      ? ` title="${escapeAttr(t('setup.unmodeledTitle'))}"`
      : '';
    options.push(
      `<option value="${escapeAttr(d.id)}"${d.id === selectedId ? ' selected' : ''}${title}>${escapeHtml(label)}</option>`,
    );
  }
  return options.join('');
}

/**
 * The ids of `savedDecks` that contain at least one card the rules engine
 * doesn't model yet, as a `Set` for `deckSelectOptionsHtml`'s
 * `unmodeledDeckIds`. One `GET /api/decks/{id}/coverage` per deck (the same
 * per-deck check the saved-decks list does), all in parallel, each failure
 * tolerated — a deck we can't check is simply left unmarked.
 * @param {Array<{id: string}>|null} savedDecks
 * @returns {Promise<Set<string>>}
 */
export async function loadUnmodeledDeckIds(savedDecks) {
  const decks = (savedDecks || []).filter((d) => d && d.id);
  const results = await Promise.all(
    decks.map((d) =>
      getDeckCoverage(d.id)
        .then((cov) => (cov && cov.unmodeledCount ? d.id : null))
        .catch(() => null),
    ),
  );
  return new Set(results.filter(Boolean));
}

/**
 * `<option>` list for the RULE 8/9 format `<select>` (GET /api/game/formats),
 * falling back to a lone "Commander" option before the catalogue has loaded.
 */
export function formatSelectOptionsHtml(gameFormats, selectedName) {
  if (!gameFormats || !gameFormats.length) {
    const sel = !selectedName || selectedName === 'commander' ? ' selected' : '';
    return `<option value="commander"${sel}>Commander</option>`;
  }
  return gameFormats
    .map(
      (f) =>
        `<option value="${escapeAttr(f.name)}"${f.name === selectedName ? ' selected' : ''}>${escapeHtml(f.label)}</option>`,
    )
    .join('');
}

/**
 * One card tile for a mulligan hand grid. `bottomEnabled` adds the
 * click-to-bottom affordance (London mulligan: after a mulligan, N cards
 * go to the bottom on keep).
 * @param {{instance_id: number, name: string}} o
 * @param {{imageCache?: Map, selected?: boolean, bottomEnabled?: boolean}} opts
 */
export function mulliganTileHtml(o, { imageCache, selected = false, bottomEnabled = false } = {}) {
  const image = imageCache?.get((o.name || '').toLowerCase());
  const inner = image?.small
    ? `<img src="${image.small}" alt="${escapeAttr(o.name)}" loading="lazy" />`
    : escapeHtml(o.name);
  const classes = ['card'];
  if (image?.small) classes.push('has-image');
  if (bottomEnabled) classes.push('clickable');
  if (selected) classes.push('selected-bottom');
  const toggle = bottomEnabled ? ` data-bottom-toggle="${o.instance_id}"` : '';
  return `
    <div class="gf-card-slot">
      <div class="${classes.join(' ')}" data-hover-card="${escapeAttr(o.name)}" title="${escapeAttr(o.name)}"${toggle}>${inner}</div>
      ${bottomEnabled ? `<button type="button" class="gf-card-action" data-bottom-toggle="${o.instance_id}">${selected ? t('setup.bottomDone') : t('setup.bottomAction')}</button>` : ''}
    </div>`;
}

/**
 * The win/loss line for a finished game. `meId` is the perspective player's
 * id (`view.perspective`).
 */
export function resultBannerHtml(state, meId) {
  const winner = state?.winner_id
    ? (state.players || []).find((p) => p.id === state.winner_id)
    : null;
  const youWon = !!winner && !!meId && winner.id === meId;
  const banner = winner
    ? youWon
      ? t('setup.won')
      : escapeHtml(t('setup.lost', { name: winner.name }))
    : t('setup.gameOver');
  return `<p class="server-status ${youWon ? 'ok' : 'warning'}">${banner}</p>`;
}
