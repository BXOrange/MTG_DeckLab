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
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-150 · Multi-target ("up to N", "up to X") for gain control, goad, counter and keyword grants

- **Started / last update:** 2026-10-13 / 2026-10-13
- **Goal of this run:** close the whole ticket — opt the four handler families into `_MULTI_TARGET_QUANTIFIER` and give each effect a working `count`/`target_count` param.
- **Done (built + tested):** counter (`counter_up_to`: Double Negative, Katara's Reversal, Repel Intruders, Repulsive Mutation; `CounterSpellEffect`/`CounterAbilityEffect` count/optional), gain control (`gain_control_multi`: Jace Ingenious Mind-Mage, Harness by Force, Mass Manipulation), goad (`goad_multi`: Sifa Grent +1; `those_creatures_cant_block`: Sontaran General), keyword grants (`pump_keywords_multi`: Invisible Force Field, Mogis's Marauder via `counted:devotion_to_black`, Voyager Drake via `source_kicker_count`). PARSER_VERSION 642. Tests: backend/tests/test_par150_multi_target_families.py.
- **In progress:** nothing; milestone 1 committed (four families built, verified by the orchestrator: default + `--full-cache` 13297 passed).
- **Next step:** check whether the saga-lifetime / "for as long as you control ~" steals (Scroll of Isildur, The Horus Heresy, The Super Hero Civil War, Rangers of Ithilien) share an existing duration in `game/durations.py`; if so add that duration to `gain_control_multi` as milestone 2, then decide each remaining card: cluster -> stay here, one-off -> `singletons.md` (re-probe each with `parser_probe.py blocked`).
- **Decisions:** plural "creatures and/or planeswalkers" steals remap `any` -> `creature_or_planeswalker` (a player cannot be stolen); `where X is <devotion|kicks>` is carried as a target-count selector, not a `bind`.
- **Baselines / artefacts:** PARSER_VERSION 642, coverage 21358/35046 (commander-legal 20552/32068); before: v641 21342 / 20536.
- **Known failures:** —
- **Residue:** Tishana's Tidebinder (counter-ability part done; "that permanent loses all abilities for as long as ~ remains" rider), Hideous Taskmaster (per-opponent steal + "trample, haste and annihilator 1" temp grant), Rangers of Ithilien ("lesser power" relative filter + "for as long as you control ~" steal), The Super Hero Civil War ("total mana value 6 or less" cross-target cap + saga-lifetime steal), Havoc Eater (counters = total power of creatures goaded this way), Sifa Grent -6, Oko +2 ("all creature types" grant), Warriors' Lesson (quoted-ability grant), Scroll of Isildur / The Horus Heresy (saga-duration steals).
