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

## PAR-292 · Library inspection and search

- **Started / last update:** 2026-11-23 / 2026-11-23 14:30
- **Goal of this run:** milestone M1 only (dynamic search qualities and the named PAR-285 / PAR-321 search shapes it reaches). The rest of the family stays open.
- **Done (M1, parser 1027, +15 cards, 0 regressed; probe 26,652 -> 26,667):** (A) `filter_slots` dynamic quality: "with mana value equal to / <= / >= <amount>" in a search noun phrase, any amount `parse_amount_phrase` reads, carried as `bind(n=amount){search criteria min/max_mana_value "$n"}` (no engine change; Repurposing Bay, Enigmatic Incarnation, Iron Man Titan of Innovation); "the sacrificed enchantment's / planeswalker's ..." joins the sacrificed-cost amounts (Faith Healer, bonus). (B) `, then shuffle` ending a search is no longer a connector cut (`CONNECTORS[2]`). (C) "search ... for any number of <cards>" = count `ANY_NUMBER_SEARCH_CAP` (Secret Salvage, Iname, Sarkhan Unbroken, The World Tree, Scouting Trek, Battalion Foot Soldier, Gathering Throng, Legion Conquistador). (D) "that each have mana value x" (Uncage the Menagerie). (E) name set "another creature you control" for "same name as" (`name_atoms` + `game/name_reference.py`; Pattern Matcher). Tests `backend/tests/test_par292_dynamic_search_qualities.py` (35: execution of every claimed card incl. bystanders not offered, LKI of the sacrificed object, declined "if you do"). Fast suite green.
- **In progress:** -
- **Next step:** best-sized next sub-cluster of `P2 Bibliothek`: see Residue (reveal/discard-a-card-then-search-by-that-card's-name-or-mana-value: Assembly Hall, Infernal Tutor, Disciple of Deceit, 3 cards plus the for-each same-name loops Doubling Chant, Clarion Ultimatum, Canoptek Wraith, Curse of Misfortunes) -- re-size with `parser_probe blocked` after landing a "pick a card, then search by it" primitive.
- **Decisions:** family ticket worked one sub-cluster per milestone; worktree `.claude/worktrees/par-grind-2026-11-23`, branch `ticket-grind/2026-11-23-par`; next `--full-cache` batch after 5 iterations (PAR-326 iteration 1; this is iteration 2). Dynamic bound uses the existing `bind` + `$n` substitution, not a second engine param (`mana_value_from` remains for the older rows).
- **Baselines / artefacts:** coverage 26,667 / 35,493 at parser 1027 (probe).
- **Known failures:** -
- **Residue (exact missing piece per card):**
  - Hibernation's End: the head "whenever you pay ~'s cumulative upkeep" (the search body already parses via `search_mv_measured`).
  - Instrument of the Bards: tail "if that card is legendary, create a treasure token" (a conditional on the found card, no search rider for it).
  - Night Dealings: "put that many theft counters" trigger plus exact "mana value x" with X from a remove-counters cost (peeler has no exact-X form yet).
  - Assembly Hall, Infernal Tutor: "reveal a <card> in/from your hand" as a resolution-time pick whose name feeds the search (choose_objects `reveal` + `then_specs` with a name operand); Infernal Tutor also "if you have no cards in hand, instead search ...".
  - Disciple of Deceit: "same mana value as that card" after a "discard a nonland card" pay_cost_then (discard cost with a type filter not parsed) plus the untap head.
  - Doubling Chant, Clarion Ultimatum, Canoptek Wraith: per-object "for each ..., search for a card with the same name as that <object>" loops (name per iteration, combined put).
  - Curse of Misfortunes ("doesn't have the same name as a curse attached to enchanted player"), Light-Paws ("with mana value less than or equal to that aura and with a different name than each aura you control"), Pyre of Heroes ("shares a creature type with the sacrificed creature and has mana value equal to 1 plus ..."), March of Burgeoning Life (also the green-cards additional cost; "mana value less than x" strict bound), Wild Pair ("same total power and toughness"), Ringsight ("shares a color with a legendary creature you control"), Savage Order (rider "it gains indestructible"), Alpine Houndmaster ("a card named A and/or a card named B"), The Earth King ("up to that many" after the attack-count trigger).
  - The rest of `P2 Bibliothek` (see BACKLOG.md PAR-292).
