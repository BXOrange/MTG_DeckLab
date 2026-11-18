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

## PAR-285 · Object filters

- **Started / last update:** 2026-11-18 / 2026-11-18
- **Goal of this run:** milestone 1: re-scan the `P1-C Objektfilter` package with `find-fragments`, sub-cluster it by filter slot (quality, zone, name, `another`, state adjectives, controller scope), then build the largest verified subfamily.
- **Done:** Milestone 1 (v970): "target creature with power/toughness X or less" (X = source announced {X}); `max_power_from_source_x` generalised with `max_toughness_from_source_x` (`targeting.SOURCE_X_STAT_BOUND_KEYS`), both target grammars (`subgrammars._STAT_BOUND_TAIL`, `effect_rows/shared.py` creature-quality suffix). +5 MODELED, 0 lost (Gang Up, Killing Glare, Entrancing Lyre, Finale of Eternity, Aryel). Tests `test_par285_source_x_stat_bound.py`; suite 24363 passed / 505 skipped.
- **In progress:** (nothing)
- **Next step:** group 2 (below): `with <quality>` residue = dynamic comparators ("mana value/power less than or equal to the number of X / that creature's power / ~'s power / your life total") on creature targets and mass groups; or Duskana `base power and toughness 2/2`. Run `parser_probe blocked` on the chosen regex first.
- **Decisions:** milestones commit one at a time (as for PAR-284); the orchestrator runs `--full-cache` only every fifth loop iteration, so the worker must not run it unless told to.
- **Baselines / artefacts:** v969 vollpool scan 2026-11-18: `P1-C Objektfilter` 277/271/145; v969 covered 25935 -> v970 25940. Exports `backend/data/exports/offene-fragmente-2026-11-18-v969-vollpool-*`.
- **Known failures:** (none recorded)
- **Residue:** Ranked groups (277 sentences, class MOD): (1) `with <quality>` vokabel 106 (done part: X-bound; rest diffuse: keyword with, `base power`, `time counter`, `mana value` dynamic bounds, `greatest/lowest`); (2) qualifier adjective 46; (3) `another/other` 41; (4) `from <zone>` slot 29 + vokabel 7; (5) `with <quality>` slot 22; (6) named/shares name 11; (7) tapped 7; (8) controller scope 4; attacking 3. Open X-shaped: Ent-Draught Basin (`power x` exact), mass `toughness/mana value x or less` (Zero Point Ballad, Day of Black Sun, Droning Bureaucrats). Carried from PAR-284: Duskana (`base power and toughness 2/2`), Cid (anthem head union). Aryel parsed; X-from-tap-cost execution not bench-verified.
