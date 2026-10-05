# Commander Spellbook integration

This page is the implementation reference for LLMs and maintainers working
on the local Commander Spellbook combo snapshot, deck matching, or its
Bracket-analysis signals.

## Upstream contract

Commander Spellbook publishes its complete variant/alias dataset as one
compressed JSON document:

- `https://json.commanderspellbook.com/variants.json.gz`
- Uncompressed alternative: `https://json.commanderspellbook.com/variants.json`
- API schema and operational guidance: `https://backend.commanderspellbook.com/schema/`

The snapshot has top-level `timestamp`, `version`, `variants`, and `aliases`.
Variant objects use the API's `Variant` shape (`id`, `status`, `uses`,
`requires`, `produces`, `description`, `bracketTag`, and other fields).
`uses[].card.name` plus `quantity` identify the named cards; `requires[]`
contains card-template predicates, not fixed card names; `produces[].feature`
describes the combo's output.

Use the bulk file instead of paging through `/variants/` to obtain the whole
dataset. Identify this client with a descriptive User-Agent, keep requests
sparse, and surface upstream errors (including HTTP 429) rather than
pretending an update succeeded. The project's importer only contacts the
bulk endpoint on first combo use or an explicit update.

## Local lifecycle and persistence

- `api/dependencies.py` constructs `CommanderSpellbookDatabase` lazily;
  server startup and a status check do not download anything.
- `GET /api/combos/status` reports the local snapshot without initializing it.
- The first `POST /api/combos/matches` initializes a missing or uninitialized
  database. `POST /api/combos/update` explicitly refreshes it.
- SQLite lives at `DATA_DIR/commander_spellbook.db`, separate from the
  disposable Scryfall card cache.
- Import detects gzip by its file signature and streams either compressed or
  plain JSON one top-level value at a time into a temporary SQLite staging
  database. Only a valid snapshot is synchronized into the local DB
  transactionally. Variant and alias SHA-256 checksums report added, changed,
  and removed rows; failed downloads/imports leave the old snapshot intact.
- The schema stores full canonical JSON in `variants` and `aliases`, plus an
  indexed `variant_uses` table for local name/quantity candidate lookup and
  `metadata` for source version/timestamp and last sync time.

Implementation: `backend/mtg_analyzer/services/commander_spellbook_database.py`,
`backend/mtg_analyzer/api/combos.py`, `backend/mtg_analyzer/api/dependencies.py`.

## Matching semantics and limits

Deck matching is local after snapshot initialization. Names are trimmed,
whitespace-collapsed, and case-folded; each variant is returned only when the
deck contains every fixed named use at the required quantity. This is name
matching, not Oracle-ID matching. The frontend sends canonical card names
after its existing card-resolution step.

Template requirements are returned for display, but this integration does not
evaluate their Scryfall query predicates. Treat such a match as a candidate,
not a verified combo; it must not alter the Bracket estimate. Likewise,
Commander Spellbook's `bracketTag` is editorial categorization, not evidence
that a variant is infinite.

`producesInfinite` is derived only from an explicit "Infinite" substring in a
produced feature name. The static deck analysis lists all fixed-use matches,
but a Bracket signal requires a verified two-card match, at least one explicit
infinite output, and no unverified template requirements.
The Bracket "Detected signals" panel lists every matched variant count and
shows each combo that qualifies for the project heuristic with its estimated
Bracket floor and mana-curve turn; other matched variants remain visible as
non-qualifying counts rather than being presented as evidence.

The project's "early" estimate schedules the individual combo-card mana
values against the deck's maximum per-turn mana curve. The curve uses the
exact expected number of land drops from opening-hand and turn-by-turn draws,
with fetchlands cracked when played and assumed to find a remaining land; it
does not cap the average number of lands drawn as though that were an actual
hand. It subtracts the mana the curve commits that turn to casting
accelerants, so the same mana isn't also spent on combo pieces. Combo pieces
may be cast on different turns, but unused mana does not carry forward. If
all pieces can be cast by turn 6, the heuristic raises the minimum estimate
to Bracket 4; later two-card infinite combos raise it to Bracket 3. It assumes
all combo cards are available and does not simulate draws, colored mana,
additional costs, or game states; it uses expected land drops as a mana
budget, not the probability of a specific combo hand. This is an explicit
project heuristic, not an official WotC numeric definition of "early". Do
not infer a Bracket signal from every two-card Spellbook variant.

Frontend lifecycle and display are in `frontend/src/js/analyzeView.js` and
`frontend/src/js/deckAnalysis.js`. Both local database refresh controls are in
`frontend/src/js/connectionSettingsView.js`; user-facing explanations are in
`user-docs/{de,en}/03_deck_analysis.md` and
`user-docs/{de,en}/06_settings_and_card_art.md`.

## Change checklist

When changing the API shape or matching rules:

1. Preserve lazy initialization; do not add network work to app startup or
   the status endpoint.
2. Keep the complete source JSON so new upstream fields survive refreshes.
3. Keep card-use indexing synchronized with the same snapshot transaction.
4. Test initial import, no-download status, name/quantity matching, changed /
   removed rows, and failure preservation.
5. Keep the Bracket signal narrower than the visible combo list: explicit
   infinite output, exactly two used cards, and no unverified template
   requirement.
6. Update the static-analysis help, Settings help, Engine-Status content,
   and this reference together.
