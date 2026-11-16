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

## PAR-282 · Static grammar on the shared phrase modules

- **Started / last update:** 2026-11-16 / 2026-11-16
- **Goal of this run:** whole ticket: replace the static rows' own object/count/condition regexes with `object_phrase`, `count_phrase` and the shared condition vocabulary; prerequisite for PAR-289/290/294.
- **Done (milestone 1, PARSER_VERSION 918, suite green 23264 passed):** `static_rows/object_scope.object_filter` now reads `characteristic_phrase.parse_object_phrase` (via `_shared_object_filter`, adapter keeps `first_strike` slugs, refuses bare adjectives/controller tails) instead of ~8 private regexes (power/toughness N, counters, attachment, entered-this-turn, keyword tables, subtype OR-list); only combat-specific dynamic filters stay (`power_vs_reference`, `power_lt_count_selector`, flag-word prefix, per-part `and/or` split, `parse_scope` fallback for irregular plurals like "oxen"). `KEYWORD_WORDS` widened (flanking, horsemanship, indestructible, hexproof). Combat-condition number words use `count_phrase.NUMBER_WORD_PATTERN`/`number_value` (one..ten). Masked diff vs 917: +9 gained (Duskwatch Hunter, Hero of the Dunes, Knight of Valor, Oko the Ringleader, Orcish Veteran, Rubblebelt Runner, Sacred Knight, Telim'Tor, War Falcon), 0 lost, 249 spec-shape-only changes (added `card_type: creature` noun key, lowercase subtypes, `card_type_all` for "artifact creatures"). Tests: `tests/test_par282_static_shared_phrases.py`, 6 pinned tests updated for the new shapes.
- **In progress:** nothing running.
- **Next step:** milestone 2 (in scope: the ticket names the shared condition vocabulary): (a) `_CONDITION_RES` combat `unless` conditions onto the shared count/referent conditions (translator or engine condition unification); (b) anthem scopes (`parse_scope` family) onto `object_filter` selectors in `continuous.group_selector_objects`. Baseline for the masked diff: `scratchpad/par282/m918_verify.json`. The "first strike" slug mismatch in the shared grammar is filed as BUG-70.
- **Decisions:** acceptance per milestone = version-masked full-pool spec diff; pytest `--full-cache` only at close if split into milestones (owner rule).
- **Baselines / artefacts:** scratchpad/par282/m917.json (baseline), m_a.json (918); rec.py/cmp.py/diff.py.
- **Known failures:** none.
- **Residue:** (1) `parse_scope`/`_simple_scope`/`_coordinated_scope` (anthem scopes) produce `_Scope` -> `affects` selector strings (`creatures_you_control_of_type_<x>`) for `continuous.group_selector_objects`, not `matches_object_filter` dicts; replacing them with `parse_object_phrase` needs an engine-side switch of group statics to `object_filter` selectors (ENG-sized, not a regex swap). (2) `_CONDITION_RES` (combat `unless` conditions: defending player controls/monarch/poisoned, graveyard/hand size, creature died) emit `_combat_condition_met` kinds that the shared `parse_count_condition`/referent vocabulary does not produce; `you_control_condition` already takes its object via `object_filter`. Needs a translator or an engine condition unification. (3) `anthem_patterns` regexes (ANTHEM_RE etc.) still own the subject grammar; they delegate qualifiers to `object_filter`. (4) Latent: shared `KEYWORD_WORDS` maps two-word keywords as "first strike"/"double strike" while `combat.has` compares `first_strike`/`double_strike`, so trigger/target filters with those keywords never match; fixing needs a shared-grammar slug change (not done here, adapter only). (5) Oko the Ringleader gain came from the hexproof keyword entering `KEYWORD_WORDS` ("except he has hexproof"), executed only via existing `become_copy_until_eot`; not engine-benched.
