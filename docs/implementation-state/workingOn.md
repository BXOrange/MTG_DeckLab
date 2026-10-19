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
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-166 · Shared body/state grammar residue batch

- **Started / last update:** 2026-10-19 / 2026-10-19
- **Goal of this run:** re-size each PAR-166 axis (`PARSER_LONG_TAIL.md`, "Face-audit follow-ups: PAR-166 / PAR-167") over fronts and backs at PARSER_VERSION 692, then land the highest-yield shared shapes through existing primitives.
- **Done (built + tested):** PARSER_VERSION 693 (+31 / -0 vs v692 snapshot): `where x is the amount of life you gained/lost this turn` (`_WHERE_X_AMOUNT_RE`); standing `maximum hand size is reduced/increased by N` (`static_handlers._HAND_SIZE_MODIFIER_RE` -> `hand_size_modifier`); standing colour statements (`_color_statement_specs` -> `color_change`: self / attached / group, `+N/+M and is <color>` aura); `you've cast another spell this turn` (`history_phrase`, `spell_filter.not_reference`) for self cost reductions + resolution conditions; `put a loyalty counter on ~` (`add_loyalty_counter`, source only; `test_par135_named_counters` reserved-kind pin updated for it); `target opponent chooses a <type> they control. Destroy that <type>` (`opponent_chooses_then`; `DestroyEffect.previous_subject`); `~ deals N damage to target player/opponent and each creature that player controls` (`DealDamageEffect.group_and_players="scoped_player"`). Tests: `backend/tests/test_par166_shared_body_state_family.py` (22).
- **In progress:** nothing; full-cache gate green (14772 passed, 1 skipped).
- **Next step:** orchestrator reviews, commits, closes (Done_Backend entry; BACKLOG PAR-166 residue point).
- **Decisions:** selected by the orchestrator (lowest eligible ID after PAR-132 closed; MEC-125 excluded by user). PAR-132 is closed; its leftovers are in `singletons.md` Batch 7, do not re-open them here. Exile verb of the opponent-choice edict NOT claimed (no `previous_subject` reader on `ExileEffect`).
- **Baselines / artefacts:** v692 snapshot via HEAD worktree (scratchpad); `parser_probe.py diff` = +31 / -0.
- **Known failures:** —
- **Residue:** "target X and each other Y that shares a color/type/name with it" group (Cleansing Beam, Rally the Righteous, Incite Hysteria, Surge of Zeal, Wojek x3, Leave No Trace, Bathe in Light ... ~10 cards; needs a `shares_color_with_reference` filter + target-seeded group = runtime mechanic); `where x` in a targeting-time filter ("mana value X or less ... where X is life gained": Celestine, Moseo, Rodolf, Ratchet); absolute "maximum hand size is N" (Cecily, Doctor Octopus, Null Profusion, Necrodominance, Cursed Rack; needs a set-mode on `hand_size_modifier`); multi-chooser "each opponent chooses a creature they control. <tap and goad|exile>"; edict "Exile that creature"; Ezzaroot Channeler/Licia (per-life cost reduction); Essence Pulse ("each creature gets -x/-x" is unparsed even with a fixed number); Leyline of the Guildpact ("each nonland permanent you control is all colors"); Ghostfire (spell-body "~ is colorless").
