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

## PAR-290 · Restrictions

- **Started / last update:** 2026-11-19 / 2026-11-19
- **Goal of this run:** sub-cluster `P2 Einschränkungen (can't/must/only)` by slot and build the largest clean sub-clusters milestone by milestone.
- **Done:** M1 (PARSER_VERSION 1008), ranking in `backend/data/exports/par290_rank-v1007.md`. 67 new MODELED + 7 authored-now-MODELED (version-masked full-pool diff vs HEAD: lost 0, changed 0, 12 reshaped). Built: (A) combat gate reads "blocked" (host buff + can't be blocked / max blockers / by-quality); (B) "can't attack you" on `cant_attack_defender` (engine: `attached_to_source`, `object_filter`, `active_if`, real `defender_kind` fix in `_can_attack`); (C) host activation bans (`rows_restrictions`); (D) `cast_prohibition` scope `you` + one-shot target-player cast/land bars; (E) new `land_play_prohibition` static; (F) Platinum Angel pair; (G) uncounterable scopes `creature_spells`/`subtype_spells`/`instant_sorcery_spells_you_control`; (H) `counter_placement_prohibition` rows; (I) cast-only windows/conditions (`segmenter/line_rows_cast_only.py`). Tests: `backend/tests/test_par290_restrictions.py` (110, real cards, near misses, toggles, clone, wiring-off verified for 22 switches). Suite: 25584 passed / 505 skipped; `--full-cache tests/test_par169_handler_shadowing.py` 5 passed.
- **In progress:** (nothing; M1 ready for the orchestrator to commit)
- **Next step:** M2: take the residue below in order: blocker-side "can't block creatures you control" and group one-shot "can't block this turn" (both need a blocker/one-shot restriction kind), then activate-only family and "until your next turn" attack bars.
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration and before close. A restriction is modeled only if the engine enforces it on the real card (attack/block/cast/activate legality) for exactly its subject and duration, and lifts it when the source or condition ends.
- **Baselines / artefacts:** v1007 scan: `P2 Einschränkungen` 618 sentences / 588 touched / 342 solo. v1008 rescan: 539 sentences / 516 touched / 275 solo (`offene-fragmente-2026-11-19-v1008-vollpool-*`).
- **Known failures:** (none). Review note: Codie, Vociferous Codex counts among the M1 claims only because its `{4}, {T}: Add ...` line is claimed whole by the segmenter (pre-existing hole, filed as BUG-73); its "when you next cast" rider is not modelled.
- **Residue (proposed ENG/MEC lines, 3+ cards each):**
  - MEC blocker-side restriction "can't block creatures you control / with <quality>": Spectral Grasp, Bower Passage, Storm Windrider, Heat Wave, Crow Scarer.
  - MEC group one-shot "creatures <filter> can't block this turn": Awe for the Guilds, Flash of Defiance, Ember Gale, Pyrophobia, Festival, Intimidation Bolt.
  - MEC duration "until your next turn" attack bars: Forbidding Spirit, Sivitri, Orzhov Advokist.
  - MEC "during combat" condition: Basandra, Marisi, Hand to Hand.
  - MEC chosen-quality / MV-filtered cast bars: Iona, Brisela, Spellbreaker Behemoth.
  - MEC activate-only family (timing/cost/condition on abilities): Trade Caravan, Grim Repriser, Sewer Rats, Soul Kiss.
  - PAR "can't be regenerated" (37 clauses, 2 solo; mostly non-solo, blocked by their other halves).
  - Condition vocabulary gaps (1-2 cards each, singleton candidates): Even the Odds, Tidal Influence, Checks and Balances, Grim Wanderer, Fealty to the Realm, Cloudsteel Kirin, Rite of the Raging Storm, Elephant Grass, Moonhold, Render Silent, Oriss, Spider-Punk.
