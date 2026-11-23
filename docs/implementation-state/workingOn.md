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

- **Started / last update:** 2026-11-23 / 2026-11-23 16:30
- **Goal of this run:** milestone M6 (M1 fa013937, M2 ca4ce728, M3 dc0d0131, M4 805b8d98, M5 committed); the rest of the family stays open.
- **Done (M1, committed):** dynamic mana-value bound via `bind`+`$n`, any-number searches, "that each have mana value x", "another creature you control" name set (parser 1027, +15).
- **Done (M2, parser 1028, +3 cards, 0 regressed, 0 changed IR over the 25,251 already-MODELED cards; probe 26,667 -> 26,670):** `name_reference.pick_then_search_specs`: "reveal a [<type>] card in/from your hand. Search ... same name as that card ..." and "you may discard a nonland card. If you do, search ... same mana value as that card ..." = one `choose_objects` (action reveal / discard, `pool_zones` hand, `then` = the search); the engine seats the pick as `previous_subject` (`_apply_choose_objects_tail`), so name (`name_reference` kind `previous_subject`) or mana value (`bind` over a `characteristic` operand, `filter_slots.PICKED_CARD_VALUE_PHRASE`, unreachable from printed text) is measured when the search opens. Infernal Tutor's hellbent clause = `if_else(cards_in_hand_at_most 0)` around the pick, decided before the pick (an empty hand has nothing to pick). Assembly Hall, Infernal Tutor, Disciple of Deceit. Also the "choose a <land> you control. Then search ... which have the same name as the chosen land" pick (`select_referent`), execution-tested on a probe spell. A reveal pick with no eligible card still runs the search (name undefined, finds nothing) and shuffles, via the pick's `else_effects` (RULE 701.19b); a declined discard's "if you do" skips all. Tests: 14 new in `backend/tests/test_par292_dynamic_search_qualities.py` (49 total; bystanders: instant in hand not revealable, land not discardable, other names / values in library not offered, declined discard opens no search). Fast suite green (26,125 passed, 505 skipped).
- **Done (M3, parser 1029, +8 cards, 0 regressed, 0 changed IR over the 25,254 already-MODELED cards; probe 26,670 -> 26,678):** `search_basic_or_subtype` row: "a basic land card or a <subtype> card" = `{"or": [{"basic": true}, {"type": <subtype>}]}`, tail parsed as the plain "a card" search and only its criteria swapped, so reveal / hand / battlefield [tapped] / shuffle-then-top tails are reused and an unread tail stays unclaimed. Outcaster Greenblade, Shefet Monitor, Silver Deputy, Spinewoods Armadillo (Desert), Compass Gnome (Cave), District Guide, Gatecreeper Vine, Open the Gates (Gate); Scampering Surveyor also parses (already hand-authored). Execution tests (bystanders: nonbasic land without the subtype, a land of another subtype, a nonland card; top tail checked after the shuffle; Spinewoods life gain; Shefet cycling trigger). `handler_row_order.txt` regenerated.
- **Done (M4, parser 1030, +7 cards, 0 regressed, 0 changed IR over all MODELED cards; probe 26,678 -> 26,685):** three rows in `search_control_attach.py`. `search_reveal_split`: "search ... and reveal them. Put N of them <destA> and the other <destB>. Then shuffle." (also "Shuffle, then scry 1." as `then_specs`) = positional `destinations`, refusing counts that are not N + 1. `search_reveal_mv_destination`: "Put it <A> if its mana value is N or less. Otherwise <B>" = `destination_if`. `search_reveal_condition`: "If <cond>, put it <A>. Otherwise, put it <B>" = the existing two-branch `if_else` with each branch the plain search (condition must already be in the shared grammar). Fork in the Road, Jarad's Orders, Viewpoint Synchronization, Peregrination, Flourishing Bloom-Kin, Guidelight Pathmaker, Stoic Farmer. Execution tests on a real engine (bystander nonbasic / nonland, destinations, tapped, shuffle count, condition true/false, mana value 2 vs 3). `handler_row_order.txt` regenerated.
- **Done (M5, parser 1033, +5 cards; probe 26,716 -> 26,721, 0 regressed; fast suite 26,242 passed, 505 skipped):** two rows in `search_control_attach.py`. `search_conditional_replacement`: "search ... <A>[, tail]. If <cond>, instead search ... <B>[, tail]" / "... search for 2 basic land cards instead of 1" = one `if_else` (RULE 608.2c) over two complete plain searches; a branch without its own reveal/put/shuffle tail shares the other's; "this spell was kicked" is built in the row (the kicked prefix peel cannot see an "otherwise"), every other condition goes through the shared grammar. `search_conditional_destination`: "...then shuffle and put that card on top. If <cond>, put that card <dest> instead." = the same `if_else` with the second branch the plain search to <dest>. Nissa's Triumph, Analyze the Pollen, Entish Restoration (sacrifice then the pair), Reclaim the Wastes, Embermouth Sentinel. Execution tests on a real engine (13 new: both condition branches, bystander planeswalker / nonbasic Forest / Island / spell, kicked 0/1, evidence paid / not, power 3 vs 4, Dragon vs none, declined may). `handler_row_order.txt` regenerated.
- **In progress:** -
- **Next step:** best-sized next sub-cluster of `P2 Bibliothek`: the rider on the found land after the search (Emergent Sequence, Thawing Glaciers, Land Aid '04, Unlucky Cabbage Merchant; 4 cards), or a multi-criteria single search ("a basic land card and a Shrine card", Aang's Journey: needs a per-card criteria list on `search`; grep for other "a X card and a Y card" first). Re-size with `parser_probe blocked` before choosing.
- **Decisions:** family ticket worked one sub-cluster per milestone; worktree `.claude/worktrees/par-grind-2026-11-23`, branch `ticket-grind/2026-11-23-par`; next `--full-cache` batch after 5 iterations (new run after the 2026-11-16 merge: M5 is iteration 1). Dynamic bound uses existing `bind` + `$n`, not a second engine param.
- **Baselines / artefacts:** coverage at parser 1033: 26,721 / 35,493 (probe).
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
  - M4 leftovers of the reveal-sentence family: Selfie Preservation ("if there's a tree in its art" has no engine predicate; art is not modelled), Ruin in Their Wake ("you may put ... if you control a land named wastes" is a may-gated conditional put), Verdant Mastery (puts under an opponent's control, kicker-cost condition), Scholar of New Horizons, Tithe, Nazahn (conditional put on a name), Elemental Teachings / Realms Uncharted / Threats Undetected (different-names pick, opponent chooses 2), Signal the Clans (random choice among 3 different names), Grim Reminder, Mwonvuli Beast Tracker (shuffle then top rider).
  - Aang's Journey (M5): "search for a basic land card and a Shrine card" is two different criteria in one search; `search` carries one `criteria`. The conditional wrapper itself is built.
  - The rest of `P2 Bibliothek` (see BACKLOG.md PAR-292).
