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
- Keep it terse and current — replace stale lines instead of appending. The log is one
  line per milestone, newest last.
- **On closing the ticket, delete its whole block** (the narrative belongs in
  `Done_Backend.md` / `Done_Frontend.md`); a ticket is closed only once its residue is done
  too. With no ticket in
  progress this file is just this header and the empty template — no ticket id, no log.

Block template (copy below the line, fill in):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
- **Log:** <YYYY-MM-DD HH:MM — one line per milestone>
```

---

## PAR-130 · "target `<X>` that player controls" as a target-scope slot

- **Started / last update:** 2026-09-29 / 2026-09-29
- **Goal of this run:** close the residue below.
- **Done (built + tested):** slot + trigger-head antecedent + "for each opponent/player" per-player
  rounds for triggered abilities, PARSER_VERSION 512 (narrative in `Done_Backend.md` → "PAR-130").
- **In progress:** —
- **Next step:** pick a residue cluster below; size it with
  `parser_probe.py blocked "target [a-z ,-]+ that player controls"` (71 cards still fail on a
  clause holding the phrase at v512).
- **Decisions:** "that player" composes only where the antecedent is known
  (`gate._that_player_antecedent_ok`); `TargetSpec.per_player` is gathered only on the trigger path.
- **Baselines / artefacts:** coverage 17,914 / 34,811 at v512.
- **Known failures:** —
- **Residue:**
  - *Per-player targets on the cast path:* spells/activated abilities have no per-round
    gathering, so they stay refused: Blatant Thievery, Bilbo's Burglaring, Tempted by the Oriq,
    Decoy Gambit, Mega Flare, Shellshock, Disorienting Choice, Windgrace's Judgment ("for any
    number of opponents").
  - *A prior target as antecedent:* "target opponent/player … that player controls", "target
    creature an opponent controls … another target creature that player controls": Alpha
    Brawl, Breaking of the Fellowship, Down for Repairs, Deputy of Detention, Legions to Ashes.
  - *Trigger heads not parsed:* "at the beginning of combat on each opponent's turn", "a Dragon
    you control becomes the target", "deals 6 or more damage to an opponent", "deals combat
    damage to defending player", "an instant or sorcery spell you control deals damage".
  - *Body grammar the plain target form lacks too:* "you may have it deal N damage to",
    "choose target … the player sacrifices", "noncreature permanent", "put … into its owner's
    library third from the top", reflexive "when you do, for each opponent".
- **Log:** 2026-09-29 — slot + per-player rounds shipped (+32); residue recorded here.
