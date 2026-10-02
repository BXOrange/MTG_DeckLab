// Error/warning text shown in the title bar, left of the connection
// indicator. A board's own status line sits underneath its modal overlay
// (e.g. a pending-choice dialog), so a failed action there was invisible;
// the header is never covered. One shared slot: the latest message wins,
// and clearing it (empty text) removes it.

const HEADER_MESSAGE_ID = 'header-message';

/** How long a header message stays up before it fades on its own (ms). */
const MESSAGE_LIFETIME_MS = 15000;

let clearTimer = null;

/**
 * Show `text` in the title bar, or clear the slot when `text` is empty.
 * Safe to call before/without the header element (e.g. in isolation).
 */
export function setHeaderMessage(text) {
  const el = document.getElementById(HEADER_MESSAGE_ID);
  if (!el) return;
  if (clearTimer !== null) {
    clearTimeout(clearTimer);
    clearTimer = null;
  }
  el.textContent = text || '';
  el.title = text || '';
  el.hidden = !text;
  if (text) clearTimer = setTimeout(() => setHeaderMessage(''), MESSAGE_LIFETIME_MS);
}
