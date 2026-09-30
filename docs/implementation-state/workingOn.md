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

## PAR-123 · Group-subject pronouns

- **Started / last update:** — / 2026-09-30 (v541)
- **Goal of this run:** read the group trigger's firing object in the effect types below.
- **Done (built + tested):** v528/v529: the dealer of "it deals …" under a group trigger
  (`damage_equal_to_power` and `damage` via `dealer_event_key`; Dragon Tempest's wrong claim
  fixed) and the binder resolving the group placeholder inside composition nodes. v527 the "gets +N/+M for each `<quantity>`" pump (+21;
  `_bound_pump_for_each`). A bare "it"/"that creature" under a group trigger is the firing
  object for `tap` / `return_to_hand` / `exile` / blink, and for the plain "it gets +N/+N [and
  gains `<keyword>`] until end of turn" / "it gains `<keyword>`" pump
  (`PumpEffect.trigger_subject`).
- **In progress:** —
- **Next step:** add each effect type as it is exercised, and execute the card, as
  `test_par123_group_pronoun.py` does.
- **Decisions:** a bare "it" under a `self_or_group` subject stays refused by the composed head
  (Kappa Cannoneer is correct only because "~" is named first).
- **Baselines / artefacts:** —
- **Known failures:** —
- **Residue:**
  - "for each other …" *under a group trigger* needs a count referent that is the firing
    creature, not the source (Shared Animosity's "…that shares a creature type with it" is the
    same gap). Other where-X amounts (Altar of the Goyf's "card types among cards in all
    graveyards", Ashroot Animist's "~'s power") are count-phrase gaps, not pronoun gaps.
  - "it fights up to 1 target creature you don't control with the same mana value" (Boxing
    Ring — the "with the same mana value" target filter is the gap); `copy_permanent`.
- **Log:** 2026-09-29 — residue migrated from `BACKLOG.md`. 2026-09-29 — v527: for-each pump. 2026-09-29 — v528/v529: group-trigger damage dealer,
  nested placeholder fix. 2026-09-30 — v541: "it gets +X/+X, where X is …" for the group /
  self / previous pronoun (+5); suite + full-cache green, coverage docs synced (18,170).
