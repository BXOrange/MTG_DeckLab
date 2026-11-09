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
- **Done (built + tested, 23 new tests in test_par249_token_names_creating_card.py):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## BUG-57 · "Target creature" can't choose the source

- **Started / last update:** 2026-11-09 / 2026-11-10
- **Goal of this run:** let a plain `target creature` / `any target` choose the ability's own source (RULE 115.1, 603.3d), keeping the exclusion only where the text says "another" / "other". Two milestones: (1) parser marker, no behaviour change; (2) engine flip.
- **Done (built + tested):** MILESTONE 1 (parser marker `excludes_source`, PARSER_VERSION 861, lock regenerated, nothing reads it). `handlers._stamp_excludes_source` marks every effect a clause builds that announces a target when the clause matches `subgrammars.OTHER_TARGET_PART_RE` ("another/other/any other/a third target", "up to N other target(s)") or `OTHER_THAN_SOURCE_RE` ("target ... other than ~/this X"); recurses into nested `{type, params}` bodies; an escalating clause marks only its `distinct_from_others` requirements. `EXCLUDES_SOURCE_PARAM` lives in `clause_primitives`. Carried through two whitelists that re-read specs: `flicker_sequences` (blink) and `duration_composition._retime` (pump). Phyrexian Vindicator's reflexive rider carries the marker in `rider`. New test `backend/tests/test_bug57_excludes_source_marker.py`; 20 old exact-spec tests gained the marker (each is an "another" text, RULE 109.5).
- **Proof (full pool, base = worktree at HEAD, scratchpad `dump.py`/`cmp.py`/`sweep.py`):** modeled 23266 -> 23266, 0 losses, 0 gains, 0 coverage diffs; 380 cards' specs differ, all 380 only by the marker. MODELED abilities with an other/another phrase: 342 stamped, 5 unstamped (4 are `equip`/keyword lines whose raw_text is the whole card line and which have no effects, 1 is Callidus Assassin whose quoted granted line is parsed later by `granted_line_specs` -> parse_oracle, so it is stamped there). 192 loose "another" hits unstamped are all not a target phrase (trigger conditions, sacrifice costs, "all other creatures with the same name", "other than that creature" = `excluding_trigger_subject`, Backup "if that's another creature"). Over-marking: 48 stamped abilities also contain a plain target; mostly separate effects/sentences, ~15 are one multi-requirement effect (Blood Feud, Pit Fight, Ulvenwald Tracker, Yoshimaru, Razia, ...). A marked multi-requirement effect marks the whole effect; milestone 2 must apply it per requirement (fight: the `other_kind`; fighter `creature_you_control` is source-inclusive anyway).
- **In progress:** milestone 1 verified by the orchestrator (quick suite 19514 passed; `--full-cache` 20013 passed / 4 skipped) and committed; milestone 2 not started.
- **Next step:** MILESTONE 2 on the orchestrator's go: `TargetSpec.exclude_source` + `targeting.stamped_specs` hook reading the effect's marker (set in `EffectRegistry.create` / `binding.build_effects`), flip `TargetFrame.exclude_source` default and the `creature`/`permanent`/`any`/`attacking_or_blocking_creature` branches to include the source unless marked; `other_*`/`another_*` frames, Auras (RULE 303.4d), Equipment (301.5c), reconfigure keep excluding; carry `excludes_source` from the Vindicator `rider` into the reflexive damage params (`damage_death_mixin` ~2390); tests per the ticket.
- **Decisions:** coordinator approved a single ticket in two milestones; BUG-56 committed (647b42e7).
- **Baselines / artefacts:** PARSER_VERSION 861; `--full-cache` 20013 passed / 4 skipped with milestone 1.
- **Known failures:** none.
- **Residue:** none yet.
