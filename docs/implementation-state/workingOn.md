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
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```


## PAR-231 · Trigger/cost heads: quantity threshold `<n> or more`

- **Started / last update:** 2026-11-05 / 2026-11-05
- **Goal of this run:** make the `<n> or more` quantity-threshold head grammar parse (trigger heads such as "whenever <n> or more creatures you control attack", "deals combat damage to <n> or more blocking creatures", "<n> or more counters are removed"; cost heads "remove <n> or more counters") wherever the engine has or can cheaply get the event aggregation, so head-only cards become MODELED.
- **Done (built + tested):** v831: quantity-threshold ATTACK heads (`_parse_quantity_attack_head`; named-defender forms read the new per-defender `ATTACKERS_AT_DEFENDER` event fired by `_fire_player_attacked_events` (one per attacked player/planeswalker, so Horn/Landroval/Bitter Work/Oath trigger once per qualifying defender; `at_defender` scope, `trigger_quantities._defender_group_ok`); review fix 2026-11-05) and BLOCK heads (`_block_quantity_head`, trigger `related_min`; `BLOCKS` event carries `blocked_ids`/`final_block`). Tests `tests/test_par231_quantity_threshold_heads.py` (33, incl. 3-player Horn/Oath/Bitter Work execute tests). Rulings of all 11 cards checked; Lairwatch Giant's ruling about a late extra block (effects forcing more blocks after declaration) is not modelled (trigger only at declaration). Diff +11 / -0: Amphibious Kavu, Bitter Work, Dwarven Soldier, Hedron Blade, Horn of the Mark, Lairwatch Giant, Landroval, Oath of Kaya, Rashka the Slayer, Rigo Streetwise Mentor, Serra Inquisitors. **v832:** `you put N or more <kind> counters on X` (COUNTER + `by_you` + `event_minimums.amount`), `N or more <kind> counters are removed from ~` (new aggregate `COUNTERS_REMOVED`, fired by `add_counters` with amount<=0), loyalty-ability costs now fire COUNTER / COUNTERS_REMOVED (`GameEngine._pay_loyalty_cost`, no replacement offered as before), `1 or more nonland cards are milled` (`CARDS_MILLED.nonland_count`, any player). Tests `tests/test_par231_counter_batch_heads.py` (21). Diff vs 831 base +7 / -0: Defiant Greatmaw, Inspired Tethermage, Mirelurk Queen, Nest of Scarabs, Regenerations Restored, Stocking the Pantry, Terrasymbiosis (the real heads are almost all `1 or more`).
- **In progress:** — (v832 counter-batch + nonland-milled milestone verified: full-cache 19,114 passed, committed)
- **Next step:** remaining zone-batch heads need new batch events (exile / put into library / returned to hand, each its own aggregation), or damage-batch heads; see Residue.
- **Decisions:** selected by orchestrator: highest head-only SOLO among PAR-231..236 (≈45 solo over 49 distinct heads in a `composition heads --top 300` run at v830).
- **Baselines / artefacts:** PARSER_VERSION 830 at start, 832 now (831 committed 59f8dd89); base snapshot in session scratchpad; head list in session scratchpad (not versioned).
- **Known failures (corrected; final full-cache recheck pending):** —
- **Residue:** zone-batch heads needing new engine batch events: Rakshasa Vizier (put into exile from your graveyard, 'that many'), Stonebinder's Familiar (put into exile during your turn), Tameshi (noncreature permanents returned to hand from the battlefield), Dutiful Knowledge Seeker / Wan Shi Tong (put into a library from anywhere), The Heron Moon, Zone of Flame (EXILE fires per card today); Screeching Scorchbeast (head + nonland_count in place, but the 'you may create that many ... do this only once each turn' bind body is not claimed by the gate); Sand Scout (head parses, body 'red, green, and white' token unclaimed); damage-batch heads (`deals damage to N or more creatures`, `N or more opponents are dealt noncombat damage`, `N or more pirates deal damage`); `+1/+1 counters on 2 or more other heroes` (multi-recipient); Flummoxed Cyclops body `can't block this combat`; Master's Guidance/Craig Boone body gaps; `N or more creatures you control become blocked`, `N or more of your opponents are attacked`, tap/lose-life/vampire-enter singletons. Lairwatch Giant: claimed, but its ruling's late case (blocks <2 at declaration, an effect later makes it block more) is not modelled.
