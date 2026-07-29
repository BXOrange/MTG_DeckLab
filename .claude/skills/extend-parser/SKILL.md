---
name: extend-parser
description: Extend the oracle-text parser in backend/mtg_analyzer/parser/oracle/ — add or widen an effect/static/trigger handler so more cards become MODELED. Use when asked to raise parser coverage, close a PAR-* backlog ticket, make specific cards playable/parse, add a handler for an oracle template, or work the parser long tail. Ships parser_probe.py, which answers "which real cards would this actually unlock" and "did my regex break anything" in ~5s each against the full 34k-card cache.
---

# Extending the oracle parser

The pipeline is `normalize` → `segmenter` → `catalogue/handlers` →
`gate.parse_oracle`, fail-closed: a card is `MODELED` only when **every** one
of its clauses is claimed. That gate is what makes naive parser work expensive
— a handler that looks like it unlocks 200 cards routinely unlocks 5, and a
widened regex silently breaks cards nobody was looking at.

`scripts/parser_probe.py` (in this skill) exists to make both of those facts
visible in seconds instead of at review time. A full re-parse of the cache is
~4s, so **never reason about which cards a change affects — measure it.**

```bash
cd backend && source venv/bin/activate     # or use venv/bin/python directly
PROBE=../.claude/skills/extend-parser/scripts/parser_probe.py
```

## The loop

### 1. Pick the target, then check what it's really worth

```bash
python $PROBE rank --top 40                  # live processing list
python $PROBE rank --grep 'monstrous'        # ranked, filtered to a family
```

Then — **always, before writing any regex** — find out how many of those cards
a handler would genuinely finish:

```bash
python $PROBE blocked '<regex over unclaimed clauses>'
```

It splits the matching cards into **SOLO** (this is their only unclaimed
clause → the handler makes them `MODELED`) and **ALSO BLOCKED** (they stay
`UNMODELED` regardless), prints the other clauses holding the second group
back, and ranks that residue. Typical result: a template ranked at 27 cards is
a solo blocker on 5. Two lessons fall out of one command — the ranking is an
upper bound, and the residue ranking usually names the *next* handler, so
taking two adjacent ones together is often worth several times either alone.

If the ranked template is a **block wrapper** (`choose <n> —`, a Saga chapter,
a Class level), it is usually a red herring: `gate.py` fail-closes the whole
block when one mode body fails and appends *every* body to `unclaimed`. Run
`blocked` on it and read the real failing sub-clause before believing it.

### 2. Diagnose before writing

```bash
python $PROBE card "Arbor Colossus"     # raw → normalized → specs → UNCLAIMED
python $PROBE clause "Destroy target creature with flying an opponent controls."
```

`clause` prints the normalized text (**write the regex against that, not the
printed text**), the verdict under each of the three subject modes, the
segmenter's own verdict, and — the part that saves the most time — **which
existing handlers match a prefix of the clause and what they left over**:

```
  destroy_creature_filter   consumed 35/57, left: ' an opponent controls.'
```

That is the row to widen. Prefer widening an existing row over adding a
near-duplicate one; a new row for a shape an existing row almost covers is how
this table gets hard to reason about.

### 3. Write the handler

Patterns, whitelists and the anti-over-match rules: **[reference/handler-recipe.md](reference/handler-recipe.md)**.
Read it before editing — it lists the shared sub-grammar macros to reuse, the
three registries a new effect type must be added to, and which file each kind
of clause belongs in (`handlers.py` vs `static_handlers.py` vs `segmenter.py`).

### 4. Prove it, including what you didn't intend

```bash
python $PROBE snapshot /tmp/base.json     # BEFORE your edit (or: git stash, snapshot, pop)
# ...edit...
python $PROBE diff /tmp/base.json
```

```
+41 newly covered / -745 REGRESSED
```

A non-zero `REGRESSED` means the regex over-matched and stole clauses from a
handler that was modeling them correctly. **Fix it before shipping** — this is
the failure mode plain pytest will not catch, because those cards had no tests.

Also spot-check that the newly-covered cards are covered *correctly*: coverage
counts claims, not correctness. Take three names off the `+` list and run
`python $PROBE card "<name>"` to read the emitted specs.

### 5. Tests — parse **and** execute

Add to a `backend/tests/test_*_family.py` (new file for a new family, matching
an existing one's style):

- **parse**: `match_clause("<normalized clause>")` emits the expected
  `EffectSpec`s — plus the adversarial case, an almost-matching clause that
  must *not* be claimed.
- **execute**: build a `GameEngine`, bind via `bind_from_catalogue`, resolve
  the effect, assert the board changed. Parse-only tests have twice shipped
  families that crashed on first real use (a `TYPE_CHECKING`-only import, a
  `legal_targets` branch silently returning `[]`).
- **end-to-end**: `parse_oracle(real_card).modeled is True` for a real card
  from the SOLO list.

```bash
python -m pytest -q                       # whole suite, fast, keep it green
```

### 6. Close the loop — same session, no exceptions

- [ ] **Bump `PARSER_VERSION`** in `parser/oracle/gate.py`. The coverage ledger
      is keyed on content-hash **+ version**; measuring twice in one batch
      without a bump silently reuses the first run's rows. If you add more
      handlers after already measuring, bump *again* (or delete that version's
      rows). Hand-authoring alone needs no bump.
- [ ] **Authoritative measurement**: `python scripts/coverage_report.py --top 40`
      (ledger-backed — the probe is not a substitute for this).
- [ ] **Sync the number in all three places**, they drift:
      `CLAUDE.md` ("Implementation state"), `docs/implementation-state/PARSER_LONG_TAIL.md`
      ("Where coverage stands"), and `frontend/src/js/implementationStatusView.js`
      (~line 364, `'Gesamtabdeckung Oracle-Parser (…)'`, German decimal comma).
- [ ] **Backlog discipline**: closing a ticket = *deleting* it from
      `BACKLOG.md` and appending the narrative to `Done_Backend.md`. No `[x]`,
      no "shipped" note, no pointer left behind. If only part is done, keep
      only the part that isn't.
- [ ] **Sweep for what else your new primitive closes.** If this batch built a
      new engine primitive, grep `BACKLOG.md` for other tickets that same
      primitive would now close or narrow, and update them in this pass. This
      repo has repeatedly built a primitive for card A and left card B's ticket
      reading "blocked on a new primitive" for three more rounds.
- [ ] A ticket deferred a **second** time must be hand-authored in
      `game/ability_catalogue.py` as the sanctioned stopgap, or explicitly
      promoted to next-up. It must not roll silently to a third deferral.

## When to stop parsing and hand-author

A genuinely singleton card is `game/ability_catalogue.py`'s job
([authoring guide](../../../docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)),
not the parser's — but only after `blocked` shows no nearby cluster. The
opposite error is just as common: a "bespoke" card is often two clauses away
from a family that already exists.

## Hard rules

- `parser/oracle/**` must have **no `game/` imports** — it is the security
  boundary. Specs are whitelisted `type` strings + clamped params; nothing
  derived from card text ever becomes code. Binding is the binder's job.
- Handlers **full-match** their clause (`EffectHandler.match` uses
  `fullmatch`). A partial match claims nothing — that is the gate working.
- Never half-model. If a builder can't safely represent the clause, return
  `None`; the card stays `UNMODELED`, which is correct and recoverable.
  Guessing produces a card that resolves to nothing.
- The probe is read-only and must stay that way: it never writes the coverage
  ledger. `scripts/coverage_report.py` owns that.
