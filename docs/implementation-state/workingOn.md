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
- **Commit every iteration** (each green milestone: sub-step built + tested), not only at
  ticket close; update the block first so the commit carries the current state. Stage only
  your own files (see the shared-tree note in memory), never `git stash`.
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
- **Done:** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <the exact next action a fresh session takes>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## MEC-145 · Recorded referents of cost and effect objects

- **Started / last update:** 2026-11-20 / 2026-11-20
- **Goal of this run:** M1: last-known-information stamps (RULE 608.2h) for discard, exile (graveyard / top of library / linked exile), tap and reveal costs, mirroring the `sacrificed_cost_*` stamps, read by `continuous.count_selector` / `effect_amounts`, plus the parser binding of `where X is the <noun>'s <characteristic>`; then the effect-produced referents, the amassed Army (PAR-284 close), the PAR-285 / PAR-286 cost cards.
- **Done (M1, PARSER_VERSION 1016, not closed):** `game/cost_referents.py` + `GameObject.cost_referents` (kind -> records of mana value / power / toughness / card-type count, snapshotted as the cost moves the object, reset per payment, plain dicts so clone/undo keep them); stamped by activation costs (discard incl. random, exile from graveyard / top of library / Food Chain creature exile, tap others, sacrifice) and spell additional costs (discard, exile from graveyard, tap others, sacrifice, sacrifice count); read by the `cost_referent_<kind>_<stat>` count-selector family. Parser: `count_phrase.parse_cost_referent_term`, `gate._cost_referents_ok` (cost text / `additional_cost` must hold the verb), `effect_body.respell_effect_produced_referents` (an earlier instruction of the same body -> existing `this_way_sum` pool), `overrides_and_amounts._THIS_WAY_SINGLE_RE`, tap cost "other than ~". Claimed + engine-executed incl. the LKI case (`tests/test_mec145_cost_referents.py`, 21 tests): Volrath the Fallen, Necropolis, Impelled Giant (tapped creature destroyed before resolution), Keldon Battlewagon, Slumbering Tora, Flesh // Blood, Ruinous Intrusion (exiled artifact MV), Spellbound Dragon (discard shape), plus Corpse Lunge, Dread Defiler, Mercurial Chemister, Pyromancy (random discard), Ninja's Blades (granted trigger, executed), Shadowheart, Dark Justiciar ("that creature's power" after a sacrifice cost, respelled onto the existing `sacrificed_cost_power` by `activation_clauses.name_sacrificed_cost_creature`, refused when the effect has its own target). Orchestrator review: a spell copy now carries `cost_referents` (`copies_mixin._SPELL_COPY_CHOICES`, RULE 707.10; test `test_a_copy_of_the_spell_keeps_the_exiled_card_referent`). Tests: 24 in `tests/test_mec145_cost_referents.py`. Probe diff vs 1015 HEAD worktree: +14 newly covered, 0 regressed. The `revealed` kind exists in `cost_referents` but no cost records it and the parser does not spell it ("the revealed card" has its own `REVEALED` reading, PAR-284 test guards it).
- **Done (M2, group 0):** per-activation referents. `StackItem.cost_stamps` snapshots `cost_referents.ACTIVATION_COST_STAMPS` (the records plus all `sacrificed_cost_*` / `discarded_cost_*` scalars) at activation; `resolve_top_of_stack` binds them onto the source for the resolution (`cost_referents.bound_to_resolution`, mirrors the `x_paid` rebinding); ability copies deep-copy the snapshot (RULE 707.10); clone/undo keep it (plain dicts on the item). Tests: Volrath 5-MV then 2-MV on the stack, deepcopy of the engine mid-stack, sacrificed scalars. Known limit: a resolution that pauses for a player choice resumes outside the binding and reads the source's live stamps.
- **Done (M2, groups 1-3):** (1) Manticore stays unclaimed: `pay_cost_then` plain discard auto-picks and records nothing (test asserts it). (2) Draconic Intervention claimed (additional cost 'exile an instant or sorcery card' either-type word; `BindEffect` hands its damage hit set back so the die-to-exile rider arms; executed with the exiled card's MV as X). Reveal-cost cards (Disaster Radius, Induce Despair) stay open: reveal needs choice plumbing. Essence Burn: the rider cannot arm through a for_each-wrapped damage, so it stays unclaimed (test). (3) `linked_exile_<stat>` selector (`gate._link_exile_referents`, `continuous.count_selector`, `GameState.linked_exile_visits`): Bishop of Binding, Drach'Nyen, Venom Deadly Devourer, Redemptor Dreadnought (optional exile additional cost now links via `track_exiled_with`), each executed on a real engine incl. the card having left its zone. Venom, Deadly Devourer is the real backlog Venom. PARSER_VERSION 1017, probe diff +5 / 0 regressed.
- **Not attempted (blockers):** (4) Foul Renewal, (5) sacrificed-set aggregates (Sword of the Ages, Vicious Betrayal, Emrakul's Evangel), (6) Minsc & Boo, (7) PAR-284 amassed Army, (8) PAR-285 re-probe: not started this run, no new blocker found; sizing still to do.
- **Next step:** (0b) a resolution that pauses for a player choice resumes outside `bound_to_resolution` and reads the source's live stamps: re-bind `item.cost_stamps` on resume (wherever the paused stack item continues, `continuations.resolve_choice`), with a test of an activated ability that pauses mid-resolution after a second activation was paid. Then size and build in order: (4) Foul Renewal (returned-from-graveyard referent: the `returned` pool is only the battlefield bounce); (5) sacrificed-set aggregates (Sword of the Ages total power, Vicious Betrayal, Emrakul's Evangel count: "any number of" sacrifice costs plus a cost-side "sacrificed this way" spelling; the `sacrificed` records already sum); (6) Minsc & Boo (reflexive "When you do" after a loyalty-cost sacrifice); (7) PAR-284 amassed Army (Foray of Orcs has no spec; Surrounded by Orcs, Goblin Plate Mail, Grishnákh need rows; `AmassEffect` already appends the Army to `context.created_objects`); (8) PAR-285 sacrificed-permanent cards (Fatal Grudge, Nahiri's Sacrifice, ...): re-probe each.
- **Decisions:** One generic record structure on the holder (spell or ability source), summed per kind, instead of one stamp per card; effect-produced referents reuse the existing "<verb>ed this way" pools (`this_way_sum`) rather than a second structure, the parser picks by whether an earlier instruction of the same body produced the object, otherwise the cost reading is checked against the cost at the gate (fail closed). The old `sacrificed_cost_*` scalar stamps stay for their existing readers; the new `sacrificed` records are additive.
- **Baselines / artefacts:** PARSER_VERSION 1015 at start, 1016 now (lock re-pinned). Baseline snapshot of HEAD parse via a HEAD worktree (scratchpad).
- **Known failures:** none. M2 tree: plain suite 25,857 passed / 505 skipped (`--full-cache` next after loop 6; M1 tree: 26,346 passed / 4 skipped).
- **Residue:** groups 0b and 4-8 (see Next step). Blocked, not attempted again until a primitive exists: Mount Velus Manticore (`pay_cost_then` auto-picks a plain discard and records nothing, plus reflexive "when you do"; a test pins it unclaimed); Disaster Radius, Induce Despair (reveal additional cost needs a chosen hand card: `reveal_from_hand` is only a payability check); Essence Burn (damage inside a `for_each` cannot arm the "exile it instead" rider; pinned unclaimed); Phyrexian Devourer (cost reading parses, its "when this creature's power is 7 or greater, sacrifice it" state trigger is unclaimed). Backlog's "Venom" = Venom, Deadly Devourer (claimed in M2).
