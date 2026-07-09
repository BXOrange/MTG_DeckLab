// Global "card detail on hover" tooltip: one floating panel, shown for
// whichever element the pointer is currently over. Deliberately built as
// event delegation on `document` rather than per-element listeners, so
// any view — present or future — opts in just by giving an element a
// `data-hover-card="<card name>"` attribute; no rebinding needed after a
// view re-renders (a common pattern here, see goldfishView.js/deckImportView.js),
// since the listener lives above the DOM nodes that come and go.
//
// Card data is read from cardImages.js's resolve cache, which is normally
// already populated for every name a view renders (a goldfish game preloads
// its whole deck up front, see goldfishView.js's `start()`). But some names
// never go through that preload — a token created by an effect mid-game
// that isn't in the deck's producible-tokens list, a DFC's back face, a
// name-casing mismatch — so on a cache miss this module also lazily
// resolves the name itself, rather than leaving the tooltip stuck at
// "Lädt …" forever with nothing left to trigger a fetch.

import { getResolvedCard, resolveCardImages, isConfirmedNotFound } from './cardImages.js';
import { cardImageUrl } from './api.js';
import { renderManaCost, escapeHtml } from './cardTile.js';

let tooltipEl = null;
let activeName = null;
let lastRenderedCard = undefined; // undefined = "nothing rendered yet", distinct from null ("known not found")
let lastEvent = null;
//: Names with a `resolveCardImages` call in flight, so a still-hovering
//: pointer (mousemove fires updateTooltip repeatedly) doesn't fire it twice.
const pending = new Set();

function ensureTooltip() {
  if (tooltipEl) return tooltipEl;
  tooltipEl = document.createElement('div');
  tooltipEl.className = 'card-hover-tooltip';
  document.body.appendChild(tooltipEl);
  return tooltipEl;
}

function renderTooltipContent(card, fallbackName) {
  if (!card) {
    return `
      <div class="card-hover-tooltip-inner">
        <h4>${escapeHtml(fallbackName)}</h4>
        <p class="empty-state">Lädt …</p>
      </div>
    `;
  }

  const manaCost = renderManaCost(card);
  const powerToughness = card.power != null && card.toughness != null ? `${card.power}/${card.toughness}` : '';

  return `
    <div class="card-hover-tooltip-inner">
      <img class="card-hover-tooltip-image" src="${cardImageUrl(card.id, 'small')}" alt="" loading="lazy" />
      <div class="card-hover-tooltip-text-col">
        <h4>${escapeHtml(card.name)}</h4>
        <p class="card-tile-type">${escapeHtml(card.type_line || '')}</p>
        ${manaCost ? `<p class="card-tile-cost">${manaCost}</p>` : ''}
        ${powerToughness ? `<p class="card-tile-pt">${escapeHtml(powerToughness)}</p>` : ''}
        ${card.oracle_text ? `<p class="card-tile-text">${escapeHtml(card.oracle_text)}</p>` : ''}
        ${card.keywords?.length ? `<p class="card-tile-keywords">${escapeHtml(card.keywords.join(', '))}</p>` : ''}
      </div>
    </div>
  `;
}

function positionTooltip(el, event) {
  const margin = 16;
  const rect = el.getBoundingClientRect();
  let x = event.clientX + margin;
  let y = event.clientY + margin;
  if (x + rect.width > window.innerWidth) x = event.clientX - rect.width - margin;
  if (y + rect.height > window.innerHeight) y = event.clientY - rect.height - margin;
  el.style.left = `${Math.max(4, x)}px`;
  el.style.top = `${Math.max(4, y)}px`;
}

function updateTooltip(name, event) {
  lastEvent = event;
  const el = ensureTooltip();
  // Re-render only when the underlying card reference changed (e.g. it
  // just finished resolving) — not on every mousemove — so a still-loading
  // card doesn't get stuck showing "Lädt …" once its data arrives while
  // the pointer is still hovering the same element.
  const card = getResolvedCard(name);
  if (card !== lastRenderedCard) {
    el.innerHTML = renderTooltipContent(card, name);
    lastRenderedCard = card;
  }
  el.classList.add('visible');
  positionTooltip(el, event);
  if (!card) resolveLazily(name);
}

// Fetch a name that never went through a view's own preload — e.g. a token
// created mid-game, or any other name miss — so the tooltip doesn't stay
// stuck at "Lädt …" with nothing left to trigger a fetch.
function resolveLazily(name) {
  if (isConfirmedNotFound(name) || pending.has(name)) return;
  pending.add(name);
  resolveCardImages([name]).finally(() => {
    pending.delete(name);
    if (activeName === name && lastEvent) updateTooltip(name, lastEvent);
  });
}

function hideTooltip() {
  activeName = null;
  lastRenderedCard = undefined;
  tooltipEl?.classList.remove('visible');
}

let initialized = false;

/**
 * Wires up the single document-level listener. Idempotent and cheap to
 * call from every view's setup — only the first call does anything.
 */
export function initCardHoverDetail() {
  if (initialized) return;
  initialized = true;

  document.addEventListener('mouseover', (event) => {
    const target = event.target.closest('[data-hover-card]');
    if (!target) return;
    const name = target.dataset.hoverCard;
    if (name !== activeName) {
      activeName = name;
      lastRenderedCard = undefined;
    }
    updateTooltip(name, event);
  });

  document.addEventListener('mousemove', (event) => {
    if (!activeName) return;
    const target = event.target.closest('[data-hover-card]');
    if (!target || target.dataset.hoverCard !== activeName) return;
    updateTooltip(activeName, event);
  });

  document.addEventListener('mouseout', (event) => {
    const target = event.target.closest('[data-hover-card]');
    if (!target) return;
    // Moving between descendants of the same hover target shouldn't hide it.
    if (target.contains(event.relatedTarget)) return;
    hideTooltip();
  });

  // Scrolling the page (or a `.scrollable` list) out from under a hovered
  // row leaves a stale tooltip pinned to a now-meaningless position.
  document.addEventListener('scroll', hideTooltip, true);
}
