import { isDeckPrintingId } from '../api.js';

// Escaping helpers shared by the game board modules.

export function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

export function escapeAttr(str) {
  return String(str).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

export function printingHoverAttr(cardId) {
  return isDeckPrintingId(cardId) ? ` data-hover-printing="${escapeAttr(cardId)}"` : '';
}
