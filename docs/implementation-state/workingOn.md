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

- **Started / last update:** 2026-11-23 / 2026-11-23 16:00
- **Goal of this run:** milestone M2 (M1 committed fa013937): "pick a card, then search by that card's name or mana value". Measured at start: `blocked 'search ... same name as that / same mana value as that'` = 7 cards (5 SOLO: Assembly Hall, Canoptek Wraith, Clarion Ultimatum, Disciple of Deceit, Doubling Chant; 2 also-blocked: Infernal Tutor, March of Burgeoning Life). The rest of the family stays open.
- **Done (M1, committed):** dynamic mana-value bound via `bind`+`$n`, any-number searches, "that each have mana value x", "another creature you control" name set (parser 1027, +15).
- **Done (M2, parser 1028, +3 cards, 0 regressed, 0 changed IR over the 25,251 already-MODELED cards; probe 26,667 -> 26,670):** `name_reference.pick_then_search_specs`: "reveal a [<type>] card in/from your hand. Search ... same name as that card ..." and "you may discard a nonland card. If you do, search ... same mana value as that card ..." = one `choose_objects` (action reveal / discard, `pool_zones` hand, `then` = the search); the engine seats the pick as `previous_subject` (`_apply_choose_objects_tail`), so name (`name_reference` kind `previous_subject`) or mana value (`bind` over a `characteristic` operand, `filter_slots.PICKED_CARD_VALUE_PHRASE`, unreachable from printed text) is measured when the search opens. Infernal Tutor's hellbent clause = `if_else(cards_in_hand_at_most 0)` around the pick, decided before the pick (an empty hand has nothing to pick). Assembly Hall, Infernal Tutor, Disciple of Deceit. Also the "choose a <land> you control. Then search ... which have the same name as the chosen land" pick (`select_referent`), execution-tested on a probe spell. A reveal pick with no eligible card still runs the search (name undefined, finds nothing) and shuffles, via the pick's `else_effects` (RULE 701.19b); a declined discard's "if you do" skips all. Tests: 14 new in `backend/tests/test_par292_dynamic_search_qualities.py` (49 total; bystanders: instant in hand not revealable, land not discardable, other names / values in library not offered, declined discard opens no search). Fast suite green (26,125 passed, 505 skipped).
- **In progress:** -
- **Next step:** best-sized next sub-cluster of `P2 Bibliothek`: "search ... for a basic land card or a <subtype> card" (Outcaster Greenblade, Shefet Monitor, Silver Deputy, Spinewoods Armadillo = desert; Compass Gnome, Scampering Surveyor = cave; District Guide, Gatecreeper Vine, Open the Gates = gate; Captain Kirk partly): about 10 cards, one `_SEARCH_NAMED_CRITERIA`-style OR of the basic filter with a subtype, plus the "reveal it, then shuffle and put it on top" / "put it onto the battlefield (tapped)" tails (measured by a signature scan of the 202 library-search-only UNMODELED cards at parser 1028; re-size with `parser_probe blocked` first). Runner-up: a rider after a basic-land search ("then if you control 4 or more lands, untap that land", "that land becomes ...", "if this spell was kicked, instead ...", about 20 cards across mixed riders, one mechanism each).
- **Decisions:** family ticket worked one sub-cluster per milestone; worktree `.claude/worktrees/par-grind-2026-11-23`, branch `ticket-grind/2026-11-23-par`; next `--full-cache` batch after 5 iterations (iteration 3 of this batch). Dynamic bound uses existing `bind` + `$n`, not a second engine param.
- **Baselines / artefacts:** coverage 26,670 / 35,493 at parser 1028 (probe).
- **Known failures:** -
- **Residue (exact missing piece per card):**
  - Canoptek Wraith: the wrapper "you may pay {3} and sacrifice it. If you do, ..." (`MAY_COST_THEN_CLAUSE` excludes a mana + self-sacrifice cost; one card). The inner choose-then-search is built.
  - Doubling Chant, Clarion Ultimatum: per-object "for each <permanent>, you may search ... same name as that permanent. Put those cards onto the battlefield" loops (a name per iteration, one combined put, then one shuffle); needs a for-each-search loop mechanism, not the pick.
  - March of Burgeoning Life: the "may exile any number of green cards" additional cost with cost reduction, and "mana value less than x" (strict bound) on a target.
  - Hibernation's End: the head "whenever you pay ~'s cumulative upkeep" (body parses).
  - Instrument of the Bards: tail "if that card is legendary, create a treasure token" (a conditional on the found card).
  - Night Dealings: "put that many theft counters" trigger plus exact "mana value x" fed by a remove-counters cost.
  - Curse of Misfortunes ("doesn't have the same name as a curse attached to enchanted player"), Light-Paws ("less than or equal to that aura and with a different name than each aura you control"), Pyre of Heroes ("shares a creature type with the sacrificed creature" plus mana value), Wild Pair ("same total power and toughness"), Ringsight ("shares a color with a legendary creature you control"), Savage Order (rider "it gains indestructible until your next turn"), Alpine Houndmaster ("a card named A and/or a card named B"), The Earth King ("up to that many" after the attack-count trigger).
  - The rest of `P2 Bibliothek` (see BACKLOG.md PAR-292).
