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
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-242 · Clone `except it has "<quoted ability>"` and Gustcloak block escape

- **Started / last update:** 2026-11-09 / 2026-11-09 13:00
- **Goal of this run:** claim the remaining `enter as a copy of ..., except it has "<ability>"` bodies listed under Residue; each body must really work or stay UNMODELED.
- **Done (built + tested):** v848, committed as a milestone. Gustcloak row `untap_self_remove_from_combat` (Gustcloak Cavalier, Harrier, Runner, Sentinel, Skirmisher). Clone exception: `enter_as_copy_tail` validates the quoted body via `segment_line` and emits `add_ability_lines` through `EnterAsCopyReplacement` and `become_copy` into `Card.granted_ability_lines`; `specs_for` parses them on top of the copied abilities; every `as_copy` inherits them (RULE 707.9a). Copycrook, Evil Twin, Mercurial Pretender claimed. `become a copy ... except it has` stays unclaimed by a guard in `keyword_actions._become_copy_of_target`. Tests: `test_par242_clone_granted_ability.py`, `test_par242_gustcloak_block_escape.py`.
- **In progress:** nothing.
- **Next step:** take each Residue body in order, starting with Progenitor Mimic (`if ~ isn't a token, create a token that's a copy of ~`, shared with Sphinx of False Conclusions). Grep for a primitive first; leave a body UNMODELED with its blocker if it can't be modelled faithfully.
- **Decisions:** Partial, not closed: the ticket names Gigantoplasm and Progenitor Mimic. Do not edit `models/cards/card.py` again without need: any byte change resets `cache/db/cards.db` (restore with `backend/venv/bin/python backend/scripts/import_bulk.py --reseed-only`).
- **Baselines / artefacts:** v848, coverage 24545/35095 (the reseeded pool dropped six token rows: Beast, Goblin // Soldier, Halfling, Pilot, Plant, Treefolk). Spec diff vs v847: 9 gained, 0 already-covered changed.
- **Known failures (corrected; final full-cache recheck pending):** none.
- **Residue:** Gigantoplasm `{x}: ~ has base power and toughness x/x` (segmenter does not claim it; Aettir and Priwen and Minsc, Beloved Ranger mention the same base-P/T phrase). Progenitor Mimic `if ~ isn't a token, create a token that's a copy of ~` (upkeep; also Sphinx of False Conclusions). Mocking Doppelganger `other creatures with the same name as ~ are goaded`. Callidus Assassin ETB `destroy up to one other target creature with the same name as ~`. Not attempted, separate shapes: The Cosplayzer, Estrid's Invocation (enchantment copy), Firion (token copy, trigger-based), and non-enter `except it has` copy forms (`copy_permanent` has no `add_ability_lines` consumer; about a dozen more cards such as Aurora Shifter, Court of Vantress, Dack's Duplicate).
