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

## PAR-161 · "Its owner puts it on their choice of the top or bottom of their library."

- **Started / last update:** 2026-10-13 / 2026-10-13
- **Goal of this run:** close the whole ticket — parse the clause and give the owner an interactive top-or-bottom pick.
- **Done (built + tested):** handler `owner_puts_library_choice` (handlers.py, "<target>'s owner / the owner of <target> puts it on their (choice of) top or bottom of their library") -> existing `owner_puts_on_top_or_bottom` (RULE 401.4 `library_position` choice, owner answers); new target kind `spell_or_nonland_permanent` (targeting.py, merged into the Sink into Stupor branch); PARSER_VERSION 640 + lock; `tests/test_par161_owner_library_choice.py` (12 tests incl. opponent-owned -> p2 chooses, stolen permanent -> owner, spell target, trailing scry). Backend suite + `--full-cache`: 13245 passed.
- **In progress:** nothing; milestone 1 committed.
- **Next step:** milestone 2 — add a chooser=controller variant ("put it on the top or bottom of its owner's library" where *you* choose: Not Forgotten, Arashin Sovereign, S.N.E.A.K. Dispatcher; Hinder via a library destination on the counter effect), then the missing target kinds (Aether Gust, Guidance Failure, Subtlety, Swat Away's target half); re-probe. Aetherspouts / Tolarian Contempt / Power of Persuasion / Ice Magic only if their other clauses turn out cheap.
- **Decisions:** —
- **Baselines / artefacts:** PARSER_VERSION 640; coverage 21335/35046 = 60.9% (v639: 21316), commander-legal 20530/32068; probe 32 -> 12 cards.
- **Known failures:** —
- **Residue:** 12 probe cards still open: "your choice" (controller picks) family needs a chooser=controller variant: Hinder (counter + library instead of graveyard, needs a CounterSpellEffect destination), Not Forgotten, Arashin Sovereign (self, "you may"), S.N.E.A.K. Dispatcher; unresolved targets: Aether Gust ("spell or permanent that's red or green"), Guidance Failure ("creature or spacecraft"), Subtlety ("creature spell or planeswalker spell"), Swat Away ("spell or creature" + cost-reduction clause), Aetherspouts ("for each attacking creature"), Tolarian Contempt ("for each opponent ... rejection counter"), Power of Persuasion (d20 table), Ice Magic (modal + shuffles clause).
