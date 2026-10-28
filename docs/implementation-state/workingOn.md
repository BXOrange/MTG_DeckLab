# Working on — resumable state of the ticket in progress

**The working memory for a ticket that is being built right now.** It exists so that a
new session — after the prompt cache expired, a crash, an update, a context compaction —
continues exactly where the last one stopped instead of re-deriving the state from the
code, the git log and the backlog.

Rules:

- **Read this file first** when you start or resume work on any ticket. If your ticket has
  a block below, continue from its *Next step*; do not re-evaluate what it records as done.
- **One block per ticket in progress**, headed `## <TICKET-ID> · <title>`. Several sessions
  may share this working tree, so never edit another ticket's block.
- **A partly done ticket's residue lives here, not in `BACKLOG.md`.** When a run ends with
  part of the ticket still open, keep its block and record under *Residue* exactly what is
  left (card clusters, blockers, which cards each needs) plus the *Next step*; `BACKLOG.md`
  keeps only the ticket's terse open point (id, title, one-clause scope).
- **Update the block at every milestone**, not only at the end: after a sub-step is built
  and tested, after a decision, before a long-running command (full test tier, coverage
  run), before a commit. Write it so a reader with *no* conversation context can act on it.
- Keep it terse and current — replace stale lines instead of appending. Keep only
  the current resumable state; session logs belong in unversioned temporary files.
- **On closing the ticket, delete its whole block.** Durable results for shared
  engine/parser features belong in `Done_Backend.md` / `Done_Frontend.md`;
  individually modeled cards stay documented in their implementations and tests,
  not in `Done_Backend.md`. A ticket is closed only once its residue is done too.
  With no ticket in progress this file is just this header and the empty template
  — no ticket id, no log.

Block template (do not change this, copy below the line, fill in there):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-215 · Referenced-object amounts and mana-value comparisons

- **Started / last update:** 2026-10-28 / 2026-10-28
- **Goal of this run:** close the ticket: `equal to its / that card's mana value / power / toughness`, `the damage dealt / prevented this way`, `the number of <counted objects>`, `with mana value x or less / less than or equal to <amount>` as operands of existing life, damage, draw, token, P/T and filter effects (`effect_amounts.py`). Scan sizes 384+316 touched / 243+143 only (v792).
- **Done (built + tested):** (A) referent amounts: `segmenter._referent_characteristic_specs` accepts `that card's` / `that spell's`, recipient-first damage (`deals damage to that player equal to ...`) and `up to one target`; new `REVEALED` referent (clause_reading.py; `produces()` yields it after `reveal_top`/`put_revealed_card`, a lone `inspect_cards` reveal, or a one-card `exile_top_of_library`, carried by the sequencing loop); `reveal_top_take` row (draw_discard_cast.py: "reveal the top card of your library and put it into your hand"); `inspection._REVEALED_AMOUNT_FOLLOW_UP` exempts "equal to its/that card's <char>" from the dangling-pronoun guard. "that spell's" binds only after a counter (COUNTERED referent); "that card's" refuses a made token (CREATED) or no picked card. (C) mana-value bounds: counter/copy spell filters `with mana value N or less/greater` (subgrammars SPELL_TARGET, `targeting._spell_matches_filter` min_mana_value, `CounterSpellEffect.max_/min_mana_value`, registry), `gain control of target X with mana value x or less` takes the announced X (Dominate). Fixes found on the way: `_peel_condition` kept only the outer gate over an inner spec's own condition (now `all`); object_phrase refuses "attach it to ~" (inverted direction, Thieving Skydiver). PARSER_VERSION 794 + lock + history; handler_row_order.txt gets `reveal_top_take`; tests/test_par215_referenced_amounts.py (23); test_par71 Draining Whelk expectation flipped to modeled.
- **In progress:** nothing; milestone 1 (axes A + C) committed at v794 — default tier 17031 passed / 487 skipped, --full-cache 17517 passed / 1 skipped (orchestrator-verified). find-fragments v794: open 9170 cards (was 9193), 13397 fragments (was 13440), covered 22778 (was 22755).
- **Next step:** open axes (see Residue), each its own batch: B damage-by-power recipients ("deals damage equal to its power to its controller / each other creature"), D relative-player counts, E dynamic mana-value bounds (`mana value equal to / less than or equal to <amount>`), F `damage dealt/prevented this way`.
- **Decisions:** referent chosen from the earlier clause's producer, never from the noun alone; wrong-but-MODELED candidates declined (Deekah token-sizing, Thieving Skydiver). `x or less` on a spell filter refused (announced X as a ceiling not modelled). Did not touch `Referent` for random-hand reveals (Planeswalker's Fury family).
- **Baselines / artefacts:** PARSER_VERSION 793 -> 794. find-fragments v793: open 9193 cards (9179 real fragment), 13440 fragments, covered 22755. Full-pool spec dumps in scratchpad (before.json, after3.json, dump_specs.py, compare.py): +27 newly modeled, 0 lost, 0 changed.
- **Known failures:** none from this ticket.
- **Residue:** see Next step; counts from the v792 scan that remain: `the number of <counted objects>` operands (~112 all-axis cards: relative-player counts "that player controls / in their hand", per-opponent), dynamic mana-value bounds ("mana value less than or equal to the number of ...", "mana value equal to the number of counters on ~": Ratchet Bomb family), `damage dealt/prevented this way` (16 clauses), bite-style recipients ("to its controller", "to you", "each other creature"), "assigns combat damage equal to its toughness", "base power and toughness each equal to its mana value", "pay life equal to its mana value" alt-costs, literal-bound filters in graveyard-return/dig/"from among them" rows (~40 clauses).
