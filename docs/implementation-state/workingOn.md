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
- **Next step:** <the exact next action a fresh session takes>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-292 · Library inspection and search

- **Started / last update:** 2026-11-23 / 2026-11-24 10:00
- **Goal:** close the generic library pieces of `P2 Bibliothek` (614 / 483 / 181 at v1054). Build a piece only when one generic part serves several cards; single cards go to `singletons.md`. Close when no such shape is left.
- **Done (M1–M24, v1027–1054, +185 library cards, +18 pile cards; detail in `Done_Backend.md` "Library inspection and search (PAR-292 ...)" / "Two-pile splits", per-milestone notes in git history of this block):**
  - M1–M10 search: dynamic bounds, hand-reveal-named searches, subtype unions, conditional replacement searches, found-card riders, other searchers, slot searches, exile searches, distinct keys, shuffle-then-top.
  - M11–M15 inspection: look/reveal-top digs with bounds and ordered bottoms, exile-and-cast picks, shuffle-into-library, reveal-until by another player, hits under the ability controller.
  - M16–M20: same-name sweeps from an earlier pick, opponent splits, "that many" digs, free-cast digs, exile-until with a free cast.
  - M21–M23: piles (library, public zones), cast pools with a cap, Aura searches attached on entry. M22 (piles over permanents) was outside the family.
  - M24: target opponent's library searches with "Then that player shuffles".
- **In progress:** -
- **Next step:** pick the largest generic shape from the backlog scope, size it with `parser_probe` / `find_fragments --axes`, build it once: (1) hand cards put on top / bottom of the library after a draw ("draw 3, then put 2 cards from your hand on top of your library in any order", 16 cards, 10 only that sentence); (2) peeking at the top card of a player's library (21, 7); (3) revealing any number of <quality> cards from hand plus its "for each card revealed this way" consumer (11, 10: the Seer cycle); (4) bare "shuffle your library" (5, 3); then the owner-scoped multi-object moves (6 + 5 + 5). Before each, check whether the blocker is really library-specific or a shared axis (back-reference, whose library, amount, condition, object filter); a shared-axis gap is fixed in the shared grammar for every family, not per card.
- **Decisions:** worktree `.claude/worktrees/par-grind-2026-11-23`, branch `ticket-grind/2026-11-23-par`; `--full-cache` every 5 iterations (last green: c876ecc2, parser 1054, 27,360 passed, 4 skipped). Generalise an existing primitive, never a parallel one. Re-scoped 2026-11-24 after the v1054 measurement: every split-off tail ("then shuffle", "put the rest on the bottom", 81 sentences) is open only through its front sentence, and about 60% of the open fronts carry a shared-axis marker.
- **Baselines / artefacts:** v1054 `find_fragments --axes --slots` (Commander-legal): pool 32,643, covered 26,418, open 6,057 cards / 9,081 sentences; `P2 Bibliothek` 614 / 483 / 181 (9th by solo cards). Library fronts by marker: back-reference 150 cards, whose library 97, amount 79, condition 70, object filter 51, none 180. Scan files in the scratchpad (`frag1054/`), not kept.
- **Known failures:** -
- **Residue (multi-card mechanisms in scope; single cards are in `singletons.md`, piles on PAR-298, outside-the-game on MEC-144, prowl on PAR-299):**
  - Owner-scoped moves: "~ and <object> into / on top of their owners' libraries" (Elixir of Immortality, Serene Remembrance, Floodpits Drowner, Void Stalker, Gomazoa, Vortex Elemental); "shuffle all permanents you own" (Lich's Mirror, Sway of the Stars, Warp World, Glimpse of Tomorrow, Collision of Realms); a target player's / each owner's graveyard shuffled (Repopulate, Loaming Shaman, Witness the Future, Turn the Earth, The Three Seasons); owner shuffles, then a follow-up in the owner's name (Zoyowa's Justice, Audacious Swap, Chaos Wrap, This Is How It Ends).
  - Loops: "for each <permanent>, search ... same name" and per-permanent search loops (Doubling Chant, Clarion Ultimatum, Dire-Strain Rampage, Krenko's Buzzcrusher, From the Ashes, Wave of Vitriol).
  - Dig shapes: reveal-then-bottom-all with no pick (Stomping Slabs, Sanity Grinding, Petals of Insight); one card per subtype slot (Harper Recruiter, Kaalia Zenith Seeker, Eivor); hits relative to a spell (Jodah, Possibility Storm, Tibalt's Trickery, Unpredictable Cyclone, Guff Rewrites History); "shuffle N <name> cards into their library" (Fludge, The Gunky Runner and the other gunk cards).
  - Known simplifications (documented, not open work): a split search with fewer finds than "chooses N" makes every find chosen; declining an exact-count may-search still shuffles; filed as bugs: BUG-81 (look-at / reveal-until cards staged in exile), BUG-82 (an Aura that can't enchant ~ enters anyway), BUG-83 (an empty same-name sweep skips the shuffle).

## PAR-291 · Player-scoped actions

- **Started / last update:** 2026-11-25 / 2026-11-25 (M1 done)
- **Goal:** close the generic pieces of `P2 Spielerbezogene Aktionen` (822 / 746 / 320 at an older version): build a piece only when one generic part serves several cards; single cards go to `singletons.md`. Close when no such shape is left.
- **Done:**
  - M1 (v1071, +14 cards, 0 lost): (a) "<player>'s life total becomes <amount>" as one row (`life_loss._SET_LIFE_TOTAL_RE`): subjects your / target player's / target opponent's / each player's / each opponent's; amounts a number, a fraction of the starting life total (`fraction_of_starting` + `round_up`), "highest / lowest life total among all players" (`resource` + `aggregate`, measured once) or "the number of <objects> they control" (`measure_per_player`). Engine: `SetLifeEffect` gained `selector`, operand `amount`, `measure_per_player`, `round_up` (registry passes them through). Cards: Arbiter of Knollridge, Biorhythm, Blessed Wind, Magister Sphinx, Repay in Kind, Shaman of Forgotten Ways, The Darkhold, The Endstone, Vraska Relic Seeker. (b) "each player / each opponent discards their hand" and the wheel "then draws cards equal to the greatest number of cards a player discarded this way" (`draw_discard_cast._MASS_DISCARD_HAND_RE`, the Windfall bind generalised): Mindslicer, Sire of Insanity, Myojin of Night's Reach, Jace's Archivist, Whispering Madness. (c) Latent false claim removed: the third-person "creates that many <tokens>" row (a trigger-event amount) is imperative-only, so Awaken the Erstwhile (each player's own discard count) is no longer claimed with amount 0. Tests `tests/test_par291_set_life_total.py` (real cards on a 3-player GameEngine, refusal cases).
- **In progress:** -
- **Next step:** build the largest remaining shape. Ranked (solo cards = every open sentence of the card is in this family): (1) a target / each opponent's non-sacrifice edict verb over "they control": "target opponent exiles a creature / an enchantment they control" (Debt to the Kami x2, Doomfall, Early Winter, Strategic Betrayal), "each player returns a creature they control to its owner's hand" (Curfew, Blizzard Specter, Blood Clock, Discovery), ~9; reuse `edicts.py` `_EDICT_POOL` + `SacrificeEffect(action="exile")` / a bounce action. (2) "each player returns all <creature/artifact...> cards from their graveyard to the battlefield" and exile-then-return mass moves (Balthor, Bloodbond March, Myr Servitor, Patriarch's Bidding, Second Sunrise, Fall of the Thran, Crypt Champion, Bringer of the Last Gift, Living End, Scrap Mastery), ~10; shared axis: whose graveyard (each owner), check `tap_return_zones.py` for the single-player form first. (3) "target player/opponent creates N tokens" (Balefang, Hansk, Eiganjo Uprising, The Sentry, Death by Dragons, Inscription of Insight, Life of the Party), 7: a `create_token` player scope. (4) "each player / each opponent exiles the top card of their library" (Pyxis of Pandemonium, Rocco, Timesifter, Triple Triad, Fathom Feeder, Memory Vessel), 6. (5) "target player reveals their hand and discards all <class> cards" (Amnesia, Shatter Assumptions, Trapfinder's Trick, Mind Extraction), 4. (6) "each player chooses ... then sacrifices the rest" (Cataclysm, Global Ruin, Stick Together, Destined Confrontation, Balancing Act), 5. (7) "for each opponent who does" payoffs of the Tempt cycle plus "you and that player each" (Tempt with Glory / Immortality, Tempting Contract, Master of Ceremonies, Cait, The River Warlock), ~6. (8) "for each player, <effect on that player>" loops (Battle at the Helvault, Krenko's Buzzcrusher, Incite Rebellion, Lim-Dul's Hex, Elminster's Simulacrum), 5. Size each with `parser_probe blocked` before building.
- **Decisions:** the largest generic shape was chosen by solo-card count over a regex sweep of the v1070 assignment file (the ticket-named "island or blue permanent" pools and "exiles cards from the top until" have about 3 solo cards each and stay in Residue).
- **Baselines / artefacts:** parser 1070 (HEAD 60d390c7) `find_fragments --axes --slots` (Commander-legal): pool 32,643, covered 26,261, open 6,214 cards / 9,303 sentences; `P2 Spielerbezogene Aktionen` 600 sentences / 543 cards touched / 242 solo cards. After M1 (v1071): parser_probe coverage 26,828 of 35,493 (+14). Scan files in `backend/data/exports/` (Git-ignored), probe snapshot in the scratchpad.
- **Known failures:** -
- **Residue:** multi-player scopes (Raging River, Stand or Fall, Butcher Orgg; Cait, The River Warlock "you and defending player each"); cross-dimension pools "island or blue permanent"; "exiles cards from the top until ..." plus cast riders (Bismuth Mindrender, Black Widow, Guff Rewrites History, Collision of Realms); life-total sets needing other machinery: "that player's life total becomes 1" on an attack trigger (Master of Cruelties, defending-player selector), "becomes that number" after a count sentence (Invincible Hymn, Touch of the Eternal), sets inside "if you would lose the game, instead ..." replacements (Exquisite Archangel, Lich's Mirror, Nira, Stunning Reversal, The Golden Throne, Enduring Angel), conditional ones (Long Rest, Elderscale Wurm), sets that follow unclaimed sentences (Sway of the Stars, Worldfire, Once More with Feeling, Oketra's Last Mercy); "each player discards, then creates that many tokens" (Awaken the Erstwhile) and "any number / that many minus 1" wheels (Flux, Dark Deal).
