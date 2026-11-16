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

## ENG-61 · Retire named-string and flat group selectors

- **Started / last update:** 2026-11-16 / 2026-11-16
- **Goal of this run:** (b) hand-authored `card_catalogue` entries off named strings/flat group params (owner request), then (a) one-shot effect `selector` vocabulary and the four parser residues, then (c) delete the named branches and flat tail in `group_selector_objects`.
- **Done (milestone 1, part b):** 210 hand-authored `card_catalogue` files (~235 sites) on structured selectors: ~175 static `affects` (grant_keyword, anthem, grant_mana_ability, grant_*_ability, type_change, combat_restriction, pt_set, untap, protection, ...), ~50 one-shot `selector`s whose reader goes through `group_selector_objects` (pump, tap, unblockable, combat_restriction_this_turn, ...), ~25 mass destroy/exile/gain_control moved from string `selector` to `group` (`_group_objects`). Flat `subtype`/`tokens`/`exclude_self`/`subtype_from_source` folded into the filter only where the handler reads them solely through `group_selector_objects`; other flat params stay beside the dict (applied after the structured branch). `tests/test_eng61_selector_equivalence.py` (56): 36 named strings, 13 flat combinations, 12 mass strings proven equal to their structured form on 3 boards x 2 perspectives. Suite 23,393 passed.
- **Done (milestone 2, part a):** readers: `activation_prohibited`/`activation_cost_changes` judge a named source through `selector_admits_object` (filter `name_from_source`, any zone); mass `destroy`/`exile`/`return_to_hand`/exile-sequence `group` path now applies `filter` (and destroy `exclude_created`) through `_mass_group_objects` = `_group_objects` + `_apply_mass_filter` (the tail `_mass_selector_objects` uses); goad and phase_out accept a structured selector; `legendary`/`nonlegendary` filter keys read layer-derived `obj.is_legendary`. Cards migrated (48): Pithing Needle, Phyrexian Revoker, Disruptor Flute, Petrified Hamlet, Drana and Linvala, Karn the Great Creator, The Immortal Sun, Suppression Field, Tithe Taker, Dauntless Dismantler, Kulrath Knight, Haunted One, Master Chef, Noble Heritage, Scion of Halaster, Tavern Brawler, Acolyte of Bahamut, Dungeon Delver, Earthshape, Halvar, Gold-Forged Thopteryx, Flowering of the White Tree, Jodah; mass destroy/exile/return (Austere Command x2, Citywide Bust, Culling Ritual, Fell the Mighty, Martial Coup, Ruination, Steel Hellkite, The Battle of Bywater, White Sun's Twilight, Winds of Rath, Final Act, Chainer, Aetherize, Llawan, Perplexing Test x2); add_counters/damage `each_*` (Nykthos Paragon, Gourmand's Talent, Shalai, Sarek, Archfiend of Ifnir, Avenger of Zendikar, Ajani Steadfast, Oran-Rief, Mazirek, Midnight Banshee, Celes, Defiler of Vigor, Vault 12, Bellowing Aegisaur, Priest of the Crossing, Ultimate Magic Meteor, Territorial Aetherkite, The Elder Dragon War, Spiteful Banditry, Chain Reaction, Blasphemous Act, Planetary Annihilation); goad/phase_out (Nelly Borca, Fast Forward, The City on the Edge of Forever). Parser: `named_card_statics` (chosen-name prohibition/tax, Alpine Moon) structured; PARSER_VERSION 922.
- **In progress:** —
- **Next step:** remaining residue before (c): (1) parser emitters still emit named strings: add_counters `each_*` (`counters_blocking.py` ~709), damage `each_creature`/`each_other_creature`/`*_and_player` (`shared.py` ~363, `damage_copy.py`), goad `suspected_creatures`/`creatures_opponents_control`, mass destroy/exile/return `all_*` selectors (`search_control_attach.py`, destroy_exile_counter.py), `emblem_statics`, effect-body `lock_group`, `counters_blocking` cant-block-turn groups (`opponents_permanents`); (2) hand-authored stragglers: Thelon of Havenwood (`all_creatures` + `object_filter`), `each_creature_and_player`/`each_creature_and_planeswalker_opponents_control` damage (Volcanic Fallout, Pyrohemia, Volcanic Torrent), Chandra's Ignition; (3) then (c): delete the named branches in `group_selector_objects`, `_mass_selector_objects` (+`_MASS_DESTROY_SELECTORS`), `_ADD_COUNTERS_SELECTORS`, `_DAMAGE_SELECTORS`, goad `_SELECTORS`, `artifacts_and_creatures`, and the `card_name_from_source` flat param branches (still read by Skyseer-style cast prohibitions/cost reductions on spells, `grant_mana_ability`). Grep proves nothing references them first.
- **Decisions:** equivalence is proven per selector shape on varied real boards, not per card; entries whose reader compares the string itself stay until (a) migrates that reader.
- **Baselines / artefacts:** masked-diff baseline `scratchpad/eng60/verify921.json`.
- **Known failures:** —
- **Residue:** see Next step. Behaviour changes: legendary filter keys read layer-derived `is_legendary` (RULE 205.4); `commander_creatures_you_own` is now `owned_by_you` (same ownership semantics); Avenger of Zendikar/Vault 12 subtype narrowing now uses `subtype_any` (granted subtypes count); mass-group iteration is player by player; Final Act "destroy all battles" now works (was inert); Haunted One/Halvar equivalent by test.
