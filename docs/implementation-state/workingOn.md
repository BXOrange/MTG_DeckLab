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
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-286 · Trigger and cost heads

- **Started / last update:** 2026-11-19 / 2026-11-19
- **Goal of this run:** milestone 1: re-scan `P1-D Trigger-/Kostenköpfe` with `find-fragments` at v986, group the open heads by shape, build the largest verified group.
- **Done:** M1 (v987): activation heads naming an actor or keyword (player/opponent "activates a loyalty / non-mana ability", "you activate a boast / eternalize or embalm ability", "an ability of a creature / Elemental / Sarkhan planeswalker" incl. mana abilities), `ACTIVATED_ABILITY.ability_keyword`, shared once-per-turn limit across list-event siblings. +7 (Burning-Tree Shaman, Gideon the Oathless, Frenzied Raider, Vizier of the Anointed, Sarkhan's Whelp, Ceaseless Searblades, Elrond), 0 lost, 0 changed. Tests: `test_par286_activation_heads.py`.
- **Done (M2, v988):** attack heads naming the defender: "attacks a battle", "attacks the player with the most life or tied for most life", "attacks the monarch" (`attacked_player_is_monarch` predicate), plus "target ... that player controls" as an object-phrase scope (event-only pools; frames apply the quality filter, audited: only The Spear uses a filter), and `create_token.attacks_event_player` so "tapped and attacking that player" attacks the event's defending player (also changes Soaring Lightbringer, 3-player tested). +4 (Thrashing Frontliner, War-Trained Slasher, The Spear of Bashenga, Seraphic Greatsword; diff in report). Tests: `test_par286_attack_defender_heads.py`.
- **In progress:** (nothing)
- **Next step:** build the delayed-linked "that creature ... this turn" group (Okoye, Barreling Attack, Captain Howler, Hunter's Insight, Maeve, Glyph of Life, Vivien's Stampede) after checking for an existing delayed-trigger primitive; or cost heads (19 solo) / one-off heads (47).
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration. A head is only real if the trigger fires in the engine: tests drive the real event. "outlast" payoffs (Herald of Anafenza) are NOT claimed: the engine binds no outlast ability.
- **Baselines / artefacts:** v986 `--all-cards --axes`: P1-D 383 sentences / 736 cards touched / 169 solo (backlog v912 scan: 383 / 757 / 161). Scan files in `backend/data/exports/offene-fragmente-2026-11-19-v986-vollpool-*`.
- **Known failures:** (none recorded)
- **Residue:** P1-D open heads ranked by SOLO cards (v986, head-shape families, long tail of one-offs): other/one-off heads 47 (e.g. "whenever you get 1 or more {E} during your turn", "whenever a permanent you control transforms"); delayed-linked "that creature / it ... this turn" 20 (Barreling Attack, Captain Howler, Hunter's Insight, Maeve, Okoye, Glyph of Life, Vivien's Stampede); cost heads 19 (Bad Ass "{1}{B}, growl", Cryptic Cruiser, Chandra's Regulator); attack/block/combat-damage subjects (M2 closed the battle / most-life / monarch ones; open: Hurska "whenever hurska attacks", Master Symmetrist "a creature you control with power equal to its toughness attacks", Mob Mentality "all non-wall creatures you control attack"; Okoye needs the delayed linked head); qualified casts 16 (mostly Un-/playtest: border, watermark, "alliterative"; real: Brimaz, Namor, Rage Extractor, Runescale Stormbrood, Pyromancer Ascension, Dovin's Acuity "during your main phase"); dies/sacrifice/leave 9; dealt-damage-by-spell 7; becomes tapped/plotted/transform 7 ("when this card becomes plotted": Aloe Alchemist, Longhorn Sharpshooter); roll/speak/Un-set 6; reflexive "when you do" 5 solo / 27 touched; "beginning of ... end step" 3 (Archivist of Gondor monarch's end step, Last Chance/Warrior's Oath "that turn's end step"). Backlog names still open: Gempalm Incinerator (head exists; body "you may have it deal X damage ... where X is the number of Goblins" is the gap), Thunderous Might / Sigil of Valor (heads exist; bodies "+X/+0 where X is your devotion to red" / "+1/+1 for each other creature you control" are the gap), Narci / Historian's Boon / Tom Bombadil (final chapter ability resolves/triggers: needs a saga-chapter event), Vivien's Stampede (delayed next main phase), Lobelia, Sapphire Charm ("at the beginning of the next turn's upkeep" delayed draw), The Spear of Bashenga ("attacks the monarch"). Satoru Umezawa (also needs ninjutsu granting) and Herald of Anafenza (outlast has no engine ability) stay open.
