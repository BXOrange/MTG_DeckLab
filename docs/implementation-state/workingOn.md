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
- **Next step:** <the exact next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-315 · Defending-player effect bodies

- **Started / last update:** 2026-11-17 / 2026-11-17
- **Goal of this run:** effect bodies that name the defending player ("defending player loses life / discards / sacrifices", "target creature defending player controls"), ~84 solo at v932, routed through the existing player-scoped effects with the PAR-313 referent.
- **Done:** milestone 1 (v933, suite 23,632 passed): line row `defending_player_trigger` (`segmenter/defending_player_trigger.py`) re-reads an otherwise-unclaimed combat-trigger body (attacks / attacks alone / attacks and isn't blocked / becomes blocked) with "defending player" as "that player"; shared `DEFENDING_PLAYER_COMBAT_EVENTS`; group / equipped / enchanted heads swap the controller operand for `attacked_player`; engine: `ATTACKS_ALONE` carries `defending_player_id`, damage `event_player` reads the defender under combat events, lose-life with an unresolved explicit operand does nothing, player referent skips the incarnation check. Masked diff vs v932: +23 MODELED, 0 lost, 0 changed, no new param keys. Tests `backend/tests/test_par315_defending_player_bodies.py` (33).
- **In progress:** -
- **Next step:** milestone 2 = "isn't blocked" riders ("if you do, ~ assigns no combat damage this turn") over "target artifact/land/creature defending player controls" / "defending player's graveyard/library" (about 12 solo); then target-restriction bodies (about 14), remaining player verbs (about 14), statics (about 10).
- **Decisions:** the defending player comes from `attack_scope.defending_player_id` / the attack event, never "an opponent"; fail closed without one; pytest `--full-cache` only at close if the ticket splits (owner rule).
- **Baselines / artefacts:** scratchpad `par315/base932.json` (masked baseline), `m933.json`, `solo.txt` (v932 probe) and `solo2.txt` (v933), `exp.py`, `ps.py`, `scan.py`.
- **Known failures:** -
- **Residue:** 63 solo (v933 probe) + 9 also-blocked; Fumulus (subtype-list head "an insect, leech, slug, or worm you control attacks") still unclaimed on its head.
