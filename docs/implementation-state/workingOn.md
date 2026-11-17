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

## PAR-284 · Amount vocabulary

- **Started / last update:** 2026-11-17 / 2026-11-17 (iteration 1, milestone 1 done)
- **Goal of this run:** size `P1-B Mengen` (331 / 328 / 213) into sub-clusters by amount form (`for each`, `where X is`, `equal to`, bare X) and land the largest shared one as one milestone.
- **Done (milestone 1, PARSER_VERSION 945 -> 946):** (1) turn-history counts: `history_phrase.parse_history_count` ("creature / Zubera / nontoken creature that died [under your control] this turn", "creature put into your graveyard from the battlefield this turn", "card / spell / food you've discarded / cast / sacrificed this turn", "the number of other spells ...") -> the existing `event_count` amount, reached from `overrides_and_amounts.count_amount` (so suffix "for each" and "where X is" share it; only when `parse_count_phrase` has no reading, so "permanents you control that entered this turn" keeps its object-count reading). (2) "for each <objects> target player/opponent controls" / "for each card in target opponent's hand|graveyard" -> `choose_targets` + `bind` with `of: target` (`overrides_and_amounts._target_player_count`; a body with its own target stays unclaimed). (3) suffix `for each` group class admits an apostrophe. Tests: `backend/tests/test_par284_turn_history_counts.py` (20: parse grammar, fail-closed phrases, engine resolution with a real turn log, Gerrard Capashen shape, Renewing Dawn shape). History entry "946", lock regenerated.
- **In progress:** nothing; milestone closed pending orchestrator commit.
- **Next step:** pick the next sub-cluster from Residue (best solo value first: "this way" tallies, then "where X" referent characteristics), probe with `parser_probe.py blocked`, implement, bump to 947.
- **Decisions:** loop runs full-cache validation only every fifth iteration (user instruction); milestones in between are validated with the default suite plus focused probes and a version-masked spec diff.
- **Baselines / artefacts:** scan `offene-fragmente-2026-11-17-v942-vollpool-zuordnung.jsonl` (325 sentences / 322 touched / 209 only at v942; v945 baseline coverage 25648/35493). Sub-clusters by amount form, sentences: `for each <count>` 176, `where X is / equal to` 149. Of the 176 for-each sentences, 36 now have a phrase `count_amount` reads; before this milestone the largest phrase groups were: turn-history counts ~16 (done), target-player counts ~16 (done), "<noun> this way" tallies ~35 (discarded/returned/counter removed/creature sacrificed/put into graveyard/goaded/countered/drawn: open), "they/that player controls" relative-player ~8, mana-spent-to-cast phrases ~8 ("color of mana spent", "mana from a treasure spent"), "color among permanents" ~5, counters on a referent ("counter on it" etc.) ~10, long singletons. Where-X 149: referent characteristics ("that creature's power / mana value", "the exiled/revealed/discarded card's mana value|toughness", "its mana value") ~35, "this way"/"this turn" tallies ~15, singletons rest. Spec diff v945 -> v946 (version-masked, full pool 35,493): +45 MODELED (39 by probe coverage + 6 hand-authored cards the parser now also models: Aetherflux Reservoir, Gadrak, Murmuration, Noise Marine, Priest of the Crossing, Volcanic Torrent), 0 lost, 0 changed; 2 UNMODELED cards changed shape (Gideon Champion of Justice, The Vegetable Car). Suite: 23,932 passed, 505 skipped.
- **Known failures:** none.
- **Residue:** (a) "<noun> <verb>ed this way" for each (card discarded 3, counter removed 2+, creature sacrificed 2, creature card put into graveyard 5, card returned/drawn/goaded/countered ~8): the engine pools exist (`effect_amounts.THIS_WAY_POOLS`) but `this_way_sequences` needs the producing first clause to parse; mostly different producers per card. (b) "where X is" referent characteristics ("that creature's power", "that spell's mana value", "the exiled card's toughness", ~35 sentences, Disaster Radius, Endrek Sahr, Morbid Bloom, Goblin Machinist, Slumbering Tora). (c) mana spent to cast ("color of mana spent to cast this spell" Sweep the Skies/Unified Front, "mana from a treasure spent", Bat Colony, Marut). (d) "they control" / "that player controls" relative counts for-each (Netherborn Phalanx, Stronghold Discipline, Emissary of Despair, Hoard Hauler). (e) "color among permanents you control" (Mondo Gecko, Soul of Ravnica, Karn Gilded Guardian), "different mana value among ..." (Lunar Insight, Sudden Insight). (f) PAR-310 residue still open: Gerrard and Hanna needs a lead effect before its chosen mode (`modes["lead_effects"]` prepended in `_resume_trigger_mode`); Gerrard Capashen and Descendant of Masumaro are now MODELED.
