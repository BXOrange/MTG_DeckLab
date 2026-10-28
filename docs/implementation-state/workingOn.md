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

## PAR-216 · Damage prevention and redirection over the shared object phrase

- **Started / last update:** 2026-10-28 / 2026-10-28
- **Goal of this run:** close the ticket: `prevent all [combat] damage that would be dealt to / by <object> [this turn]`, `a source of your choice`, `excess damage is dealt to <player> instead`, `all damage that would be dealt to <object> is dealt to ~ instead`, reusing `game/effects/replacements.py`. Scan 229 / 170 (v792). Also pick up the PAR-215 prevention leftovers (Hallow, Refraction Trap, Comeuppance, Brace for Impact, Sacred Boon, Scars of the Veteran, Immortal Coil, Ria Ivor).
- **Done (built + tested):** engine: `redirect_damage` standing replacement + `_source_relation_matches` (attached/self/blocked/unblocked/object_filter/max_amount) in `game/effects/replacements.py`; `RedirectDamageShieldEffect` + `RulesEngine._redirect_damage_shield` (one-shot redirect); `PreventDamageEffect.and_dealt_by` / `combat_only` on by-source shields; `DealDamageEffect.excess_to_controller`; `PreventDamageFromTargetEffect.spell_filter`. Parser: `catalogue/prevention_statics.py` (standing prevent/redirect over object phrases, wired into `replacements.replacement_clause_specs`), `catalogue/effect_rows/damage_prevention.py` (one-shot rows, assembled LAST in `HANDLERS` so no older row changes), static row `damage_cant_be_prevented` (global and scoped: combat / source). Also riders (`shield_deals_damage`, `if_source_creature`, delayed `add_scaled_counters`), `planeswalkers` recipient scope, scoped `damage_prevention_prohibition`. PARSER_VERSION 797 + lock + history + handler/static row-order files written. Tests `backend/tests/test_par216_{standing_prevention,oneshot_prevention,redirects_and_riders}.py` (pass). Spec diff after milestone 2: +103 gained, 0 lost, 0 changed. Milestone 2 (v798): `once` on the chosen-source shields (`RequestPreventDamageSourceEffect` / `RequestRedirectDamageSourceEffect`, `prevent_damage_to_player/_to_target(once, half)`, `redirect_damage_from_source(once, only_to_object_id)`), `protected_target_kind` (Kor Chant, Oracle's Attendants), `PreventDamageEffect` / `PreventDamageFromTargetEffect` `count_max` / `count_selector` / `combat_only`, announced-player source scope (`controller_id` in `_damage_source_matches`), two-target `RedirectDamageShieldEffect` (`recipient_target_kind`), target kind `creature_planeswalker_or_player` (redirect slot only), `DealDamageEffect.unpreventable_if` + conditional `cant_be_countered` (`_is_cant_be_countered` reads the ConditionalEffect), gate rider for Banefire / Demonfire, magnitude-override tail for Urza's Rage / Lightning Surge, `with no <kind> counters on them` in `characteristic_phrase`. PARSER_VERSION 798 + lock + history + handler_row_order. Tests `backend/tests/test_par216_residue.py`. Spec diff v797->v798: +33 gained (18 Commander), 0 lost, 0 changed.
- **In progress:** nothing; milestone 2 committed at v798 — --full-cache 17806 passed / 1 skipped (orchestrator-verified), default 17320 / 487 skipped. Spec diff v797→v798: +33, 0 lost, 0 changed. Commander covered 22971 → 22989.
- **Next step:** report to the orchestrator (Done_Backend.md / BACKLOG.md closure and Engine-Status tab note are theirs).
- **Decisions:** chosen-source "next time" forms parsed with a one-shot `once` flag (the pre-existing whole-turn `prevent all ... source of your choice` rows are the "all" forms); the parser now also claims the Circle/Rune of Protection family as `once` (hand-authored entries still persist all turn -- not changed here).
- **Baselines / artefacts:** PARSER_VERSION 796 at start. Scratchpad: `p216_before.json` (full-pool spec dump), `p216_ff_before.jsonl` (+ `-gruppen.md`) = find-fragments v796 baseline.
- **Known failures:** —
- **Residue:** "until your next turn" shields (Dovin / Kiora / Morningtide's Light, PAR-223), Ria Ivor (scaled token rider), Immortal Coil / Refraction Trap / Sivvi's Ruse / Gideon / Oko (unrelated unparsed clauses). Same-shape clauses still open and not in the listed scope: single-target combat shields over state-filtered targets ("target blocked | unblocked creature", "attacking creature with flying": `resolve_target_creature_state_filter` has no such states -- Benalish Missionary, Gossamer Chains, Songstitcher, Mirror Strike, Shimian Night Stalker), "dealt to its controller | that source's controller instead" (Mirror Strike, Reflect Damage, Reverberation), "you and/or permanents you control ... to any target" (Harm's Way, Shining Shoal, Refraction Trap), "X that shares a color with the exiled card" (Mourner's Shield), "other than" source classes (Terrifying Presence, Moonmist).
