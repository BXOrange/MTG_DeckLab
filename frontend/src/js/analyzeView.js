// "Deck analysieren" tab: placeholder nav entry ahead of the actual
// feature. POST /api/decks/{id}/analyze doesn't exist yet — see
// backend/ToDo_Backend.md "LLM Deck Analysis (UC2)".

export function renderAnalyzeView(container) {
  container.innerHTML = `
    <div class="analyze-panel">
      <h2>Deck analysieren</h2>
      <p class="empty-state">
        Die automatische Deck-Analyse (Gewinnstrategien, Archetyp, Synergien,
        Kohärenz-Score) ist noch nicht implementiert.
      </p>
    </div>
  `;
}
