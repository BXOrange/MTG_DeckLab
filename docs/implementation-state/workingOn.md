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

## PAR-288 · Small modifiers

- **Started / last update:** 2026-11-19 / 2026-11-19
- **Goal of this run:** build the shared shapes of `P1-F Kleinmodifikatoren` (`at random`, `instead`, `up to N`, order, duration) and classify the rest for close.
- **Done:** v1003 (one bump, three sub-steps). (A) `at random`: row `return_from_graveyard_at_random` (7 P1-F cards + Make a Wish; Moldgraf Monstrosity parse now equals its hand-authored spec). (B) `instead`: target-state gates, object-pronoun spelling, unannounced Aura host, bare-"it" rescoping (Bring Low, Burning Hands, Divine Smite, Elder Cathar, Grey Knight Paragon, Purifying Dragon, Sweep Away, Will of the All-Hunter, Erebos's Emissary, Everflame Eidolon); engine: bestowed object is an Aura (RULE 702.103b); Flare of Faith's gate rescoped from spell to target. (C) `up to one`: Swiftgear Drake, Conjurer's Bauble, Bilbo. Spec diff vs v1002: +21 new, +1 authored, 0 lost, 1 changed (Flare of Faith, executed). Tests: `tests/test_par288_*.py` (61).
- **In progress:** nothing; ready to close. Full suite 25153 passed / 505 skipped; `--full-cache tests/test_par169_handler_shadowing.py` 5 passed; P1-F re-measured at v1003: 44 sentences / 43 cards / 16 solo.
- **Next step:** read the closure classification (run scratchpad `par288-closure-final.md`); promote the buildable clusters it names (random graveyard exile + this-turn play window; phase out until ~ leaves; interactive alt-cost return/sacrifice payment) as PAR/MEC lines, paste the singleton rows, then close the ticket.
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration and before close. A modifier is only modeled if the engine honours it on the real card (random really random via the engine RNG, "instead" really replaces, "up to N" lets the player pick fewer, duration really ends). Kept out: Throw from the Saddle and Urdnan (override base carries more than the claimed clause), Dispense Justice (override on a separate ability-word line), Farsight Ritual (bargain "look at 8 instead" inside a dig).
- **Baselines / artefacts:** v1002 scan: `P1-F Kleinmodifikatoren` 63 sentences / 62 touched / 34 solo (`backend/data/exports/offene-fragmente-2026-11-19-v1002-vollpool-achsen.md`).
- **Known failures:** (none recorded)
- **Residue:** see the closure file.
