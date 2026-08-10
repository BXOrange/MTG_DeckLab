# `coverage` — the parser coverage ledger

**Path**: `backend/data/coverage.db` (`DATA_DIR/coverage.db`, overridable via
`MTG_DATA_DIR`). Owning service: `services/coverage_db.py`'s
`CoverageDatabase`.

**Engineering ledger, not app data** — tracks which cards the oracle-text
parser (`parser/oracle/`) currently claims `MODELED`/`UNMODELED`/
`NEVER_SUPPORTED`, or which are hand-`AUTHORED` in
`game/ability_catalogue.py` instead. Lives under `DATA_DIR` (persistent),
deliberately not `cache/` (which gets wiped on schema drift) — a full
34k-card re-measure is expensive enough that this ledger exists specifically
so it's never redone from scratch.

## Schema

```sql
CREATE TABLE card_coverage (
    content_hash   TEXT PRIMARY KEY,  -- sha1(parser_version, authored-flag, parse signature)
    name           TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    coverage       TEXT NOT NULL,     -- 'modeled' | 'unmodeled' | 'never_supported'
    source         TEXT NOT NULL,     -- 'parser' | 'authored'
    covered        INTEGER NOT NULL,  -- 1 iff modeled OR authored — the number CLAUDE.md quotes
    unclaimed      TEXT NOT NULL,     -- JSON list[str] of unclaimed clause seeds
    updated_at     TEXT NOT NULL
);
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, taken_at TEXT, parser_version TEXT,
    total INTEGER, covered INTEGER, fraction REAL, top_templates TEXT  -- JSON
);
CREATE TABLE handled_templates (
    template TEXT PRIMARY KEY, handler TEXT, handled_at TEXT
);
```

## Gotchas

- **A card can have multiple rows** — `content_hash` bakes in
  `parser_version`, so bumping it (required whenever a handler changes,
  per `CLAUDE.md`'s parser conventions) leaves the old version's row in
  place rather than overwriting it. The `coverage` convenience command
  sorts by `updated_at DESC` and flags this; raw SQL should always add
  `ORDER BY updated_at DESC LIMIT 1` or filter `parser_version = '<current>'`
  (read the current value from `parser/oracle/gate.py`'s `PARSER_VERSION`).
- `covered` is **not** the same as `coverage = 'modeled'` — it's `modeled OR
  source = 'authored'`, matching what `CLAUDE.md`'s coverage percentage and
  `scripts/coverage_report.py` actually count.
- This is a spot-check store, not an analysis tool. For ranking templates,
  live re-measuring during handler work, or diffing before/after a change,
  use the `extend-parser` skill's `parser_probe.py` instead — it never
  touches this ledger and answers those questions in seconds without a
  stale-row concern. Use `scripts/coverage_report.py` for the authoritative,
  ledger-writing measurement run once per batch.

## Examples

```bash
python $QUERY coverage "Frodo, Sauron's Bane"     # decoded, newest row flagged
python $QUERY sql coverage "SELECT coverage, COUNT(*) AS n FROM card_coverage GROUP BY coverage"
python $QUERY sql coverage "SELECT taken_at, fraction FROM snapshots ORDER BY taken_at DESC LIMIT 5"
```
