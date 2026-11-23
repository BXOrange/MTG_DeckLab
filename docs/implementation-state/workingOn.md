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
- **Goal of this run:** milestone M3 (M1 fa013937, M2 ca4ce728 committed): "search ... for a basic land card or a <subtype> card". Measured at start: `blocked` = 10 cards (9 SOLO: Compass Gnome, District Guide, Gatecreeper Vine, Open the Gates, Outcaster Greenblade, Prishe's Wanderings, Shefet Monitor, Silver Deputy, Spinewoods Armadillo; also-blocked Dance of the Tumbleweeds). The rest of the family stays open.
- **Done (M1, committed):** dynamic mana-value bound via `bind`+`$n`, any-number searches, "that each have mana value x", "another creature you control" name set (parser 1027, +15).
- **Done (M2, parser 1028, +3 cards, 0 regressed, 0 changed IR over the 25,251 already-MODELED cards; probe 26,667 -> 26,670):** `name_reference.pick_then_search_specs`: "reveal a [<type>] card in/from your hand. Search ... same name as that card ..." and "you may discard a nonland card. If you do, search ... same mana value as that card ..." = one `choose_objects` (action reveal / discard, `pool_zones` hand, `then` = the search); the engine seats the pick as `previous_subject` (`_apply_choose_objects_tail`), so name (`name_reference` kind `previous_subject`) or mana value (`bind` over a `characteristic` operand, `filter_slots.PICKED_CARD_VALUE_PHRASE`, unreachable from printed text) is measured when the search opens. Infernal Tutor's hellbent clause = `if_else(cards_in_hand_at_most 0)` around the pick, decided before the pick (an empty hand has nothing to pick). Assembly Hall, Infernal Tutor, Disciple of Deceit. Also the "choose a <land> you control. Then search ... which have the same name as the chosen land" pick (`select_referent`), execution-tested on a probe spell. A reveal pick with no eligible card still runs the search (name undefined, finds nothing) and shuffles, via the pick's `else_effects` (RULE 701.19b); a declined discard's "if you do" skips all. Tests: 14 new in `backend/tests/test_par292_dynamic_search_qualities.py` (49 total; bystanders: instant in hand not revealable, land not discardable, other names / values in library not offered, declined discard opens no search). Fast suite green (26,125 passed, 505 skipped).
- **Done (M3, parser 1029, +8 cards, 0 regressed, 0 changed IR over the 25,254 already-MODELED cards; probe 26,670 -> 26,678):** `search_basic_or_subtype` row: "a basic land card or a <subtype> card" = `{"or": [{"basic": true}, {"type": <subtype>}]}`, tail parsed as the plain "a card" search and only its criteria swapped, so reveal / hand / battlefield [tapped] / shuffle-then-top tails are reused and an unread tail stays unclaimed. Outcaster Greenblade, Shefet Monitor, Silver Deputy, Spinewoods Armadillo (Desert), Compass Gnome (Cave), District Guide, Gatecreeper Vine, Open the Gates (Gate); Scampering Surveyor also parses (already hand-authored). Execution tests (bystanders: nonbasic land without the subtype, a land of another subtype, a nonland card; top tail checked after the shuffle; Spinewoods life gain; Shefet cycling trigger). `handler_row_order.txt` regenerated.
- **In progress:** -
- **Next step:** best-sized next sub-cluster of `P2 Bibliothek`: a basic-land search whose reveal is its own sentence with the put in the next ("search your library for [up to N] basic land card(s) and reveal it/them. Put 1 onto the battlefield tapped and the other into your hand / put that card ... Then shuffle"): Fork in the Road, Verdant Mastery, Viewpoint Synchronization, Peregrination, Ruin in Their Wake, Selfie Preservation, Tithe, Scholar of New Horizons (about 8 cards; the conditional-put ones need a "put it onto the battlefield if <cond>, otherwise into hand" destination branch, so measure with `parser_probe blocked` first). Runner-up: a rider on the found land after a basic-land search ("untap that land if you control N lands", "that land becomes a creature", "return ~ at the next cleanup"; Fabled Passage, Rampaging Growth, Emergent Sequence, Thawing Glaciers, Elven Passage, Path to the Festival, about 7, one mechanism each). Sizes from a signature scan of the 193 library-search-only UNMODELED cards at parser 1029.
- **Decisions:** family ticket worked one sub-cluster per milestone; worktree `.claude/worktrees/par-grind-2026-11-23`, branch `ticket-grind/2026-11-23-par`; next `--full-cache` batch after 5 iterations (iteration 4 of this batch). Dynamic bound uses existing `bind` + `$n`, not a second engine param.
- **Baselines / artefacts:** coverage 26,678 / 35,493 at parser 1029 (probe).
- **Known failures:** -
- **Residue (exact missing piece per card):**
  - Prishe's Wanderings: the rider "when you search your library this way, put a +1/+1 counter on target creature you control". Dance of the Tumbleweeds: spree modes.
  - Canoptek Wraith: the wrapper "you may pay {3} and sacrifice it. If you do, ..." (`MAY_COST_THEN_CLAUSE` excludes a mana + self-sacrifice cost; one card). The inner choose-then-search is built.
  - Doubling Chant, Clarion Ultimatum: per-object "for each <permanent>, you may search ... same name as that permanent. Put those cards onto the battlefield" loops (a name per iteration, one combined put, then one shuffle); needs a for-each-search loop mechanism, not the pick.
  - March of Burgeoning Life: the "may exile any number of green cards" additional cost with cost reduction, and "mana value less than x" (strict bound) on a target.
  - Hibernation's End: the head "whenever you pay ~'s cumulative upkeep" (body parses).
  - Instrument of the Bards: tail "if that card is legendary, create a treasure token" (a conditional on the found card).
  - Night Dealings: "put that many theft counters" trigger plus exact "mana value x" fed by a remove-counters cost.
  - Curse of Misfortunes ("doesn't have the same name as a curse attached to enchanted player"), Light-Paws ("less than or equal to that aura and with a different name than each aura you control"), Pyre of Heroes ("shares a creature type with the sacrificed creature" plus mana value), Wild Pair ("same total power and toughness"), Ringsight ("shares a color with a legendary creature you control"), Savage Order (rider "it gains indestructible until your next turn"), Alpine Houndmaster ("a card named A and/or a card named B"), The Earth King ("up to that many" after the attack-count trigger).
  - The rest of `P2 Bibliothek` (see BACKLOG.md PAR-292).
