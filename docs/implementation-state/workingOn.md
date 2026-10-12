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

## PAR-151 · Coin flips ("flip a coin. If you win/lose the flip, …")

- **Started / last update:** 2026-10-12 / 2026-10-12 18:00
- **Goal of this run:** parser rows for the coin-flip axes onto the existing `CoinFlipEffect`/`RulesEngine.coin_flip` (and coin-flip result events): single flip with win/lose branches first, then "flip N/X coins, for each flip you win/lose", "flip until you lose", "when you win the flip" reflexive heads, branches with targets.
- **Done (built + tested):** engine: `CoinFlipEffect` recording form (`count`/`until_lose`, `MAX_COIN_FLIPS`) writing `GameContext.coin_outcome` (threaded through `_apply_effects_partitioned`/deferred/resume); `coin_won` condition; `coin_flips` amount (+ spec `won` field). Parser (PV 631): `coin_flip` clause row, `_COIN_FLIP_RESULT_RE` condition prefix (win/lose/heads/tails, negated siblings so branch targets are announced, RULE 601.2c), "otherwise" after a win branch, "for each flip you win/won/lose" (leading + suffix), "whenever you/a player win(s)/lose(s) a coin flip" (`player_event_head.py`). Fixed latent bug: `TapEffect` with `target_kind=None` untapped a sibling clause's target instead of its source (Goblin Archaeologist). Tests: `tests/test_par151_coin_flips.py` (26). Probe: +27 newly covered, 0 regressed.
- **In progress:** — (milestone 1 committed at PV 631)
- **Next step:** the per-object flip axis ("for each opponent/player/blocking creature, flip a coin": Mutalith Vortex Beast, Rakdos the Showstopper, Fighting Chance, Pandora's Box, Goblin Assassin, Mana Clash — `for_each` around `coin_flip` with per-iteration `coin_won` branches), then Breeches' reflexive head and the delayed flips (Fickle Efreet, Goblin Kites); size each with `parser_probe.py blocked` first.
- **Decisions:** selected by sizing at PV 630 (highest SOLO yield among eligible tickets; engine primitive exists).
- **Baselines / artefacts:** PARSER_VERSION 631; coverage 21,130 / 35,046 (Commander 20,346 / 32,068); coin-flip `blocked` ≈ 40 SOLO left.
- **Known failures:** pre-existing slow test — deselect `tests/services/test_bots.py::TestSearchChoices::test_a_fetch_land_is_not_wasted_declining_its_own_search` (path relative to `backend/`) when running a whole tier; full tier needs `--hard-timeout 3000`.
- **Residue:** still blocked (one-clause-each unless noted): self-damage "deals N damage to itself" (Goblin Bangchuckers, Kaboomist), Mana Screw ("activate only as an instant"), Wirefly Hive ("destroy all permanents named"), Creepy Doll ("destroy that creature" under a combat-damage-to-creature head), "flip a coin at end of combat/next end step" delayed flips (Fickle Efreet, Goblin Kites), Breeches (reflexive "when you win the flip"), Crooked Scales ("unless you pay and repeat"), "for each opponent/player/blocking creature, flip" (Mutalith, Rakdos, Fighting Chance, Pandora's Box, Goblin Assassin, Mana Clash), "choose a number / may stop flipping" (Fiery Gambit, Squee's Revenge), Game of Chaos, "flip two coins, ignore one" replacement (Krark's Thumb, Pokey), Molten Sentry (as-enters), heads/tails counts (Two-Headed Giant, Ral Zarek x2), opponent-choice/player-referent branches (Dumb Ass, Mogg Assassin, Karplusan Minotaur lose head, Planar Chaos), plus per-card bodies (Krark, Odds//Ends, Invert Polarity, Tide of War, Goblin Psychopath, Impulsive Maneuvers, Mijae/Ydwen Efreet, Skittish Valesk face-down, Goblin Festival/Lyre/Artisans).
