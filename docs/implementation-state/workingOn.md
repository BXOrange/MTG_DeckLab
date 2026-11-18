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

## PAR-285 · Object filters

- **Started / last update:** 2026-11-18 / 2026-11-18
- **Goal of this run:** milestone 1: re-scan the `P1-C Objektfilter` package with `find-fragments`, sub-cluster it by filter slot (quality, zone, name, `another`, state adjectives, controller scope), then build the largest verified subfamily.
- **Done:** Milestone 1 (v970): "target creature with power/toughness X or less" (X = source announced {X}); `max_power_from_source_x` generalised with `max_toughness_from_source_x` (`targeting.SOURCE_X_STAT_BOUND_KEYS`), both target grammars (`subgrammars._STAT_BOUND_TAIL`, `effect_rows/shared.py` creature-quality suffix). +5 MODELED, 0 lost (Gang Up, Killing Glare, Entrancing Lyre, Finale of Eternity, Aryel). Tests `test_par285_source_x_stat_bound.py`; suite 24363 passed / 505 skipped.
  Milestone 2 (v971): can't-block row carries the target quality slot (`counters_blocking._cant_block_turn`), unlocking the already-parsed dynamic power comparators (`~'s power`, `number of <things> you control`): +3 MODELED (Earthshaker Khenra, Goma Fada Vanguard, Radha's Firebrand), 0 lost, Ground Rift shape change (filter still enforced). `CantBlockEffect` now takes `creature_filter` (registry + attachments_transforms TargetSpec). Tests `test_par285_cant_block_quality.py` incl. parser->binder->legal_targets on the real cards.
  Milestone 3 (v972): "another/other target <subtype|quality|scope> [you control]": `object_phrase._target_kind` falls back to the plain kind and `_compose` stamps `excludes_source` on the `choose_targets` (registry -> `mark_source_exclusion` -> `TargetSpec.exclude_source`); "another" after an earlier target of the same ability (Hidden Strings, Toils, Tandem Takedown: distinct-from-target not modelled) stays unclaimed (`ObjectPhrase.after_target`). +26 MODELED (21 newly covered, 5 already hand-authored), 0 lost, 0 changed vs v971. Tests `test_par285_another_target_filter.py` (5 behaviour tests fail with `mark_source_exclusion` no-op'd).
  Milestone 4 (v973): sequential "another target X" (RULE 115.3): `tap_or_untap` row takes "another" (Hidden Strings, Toils; Tideforce Elemental re-shaped, equivalent), verb pair "destroy|exile|tap|untap target A and [up to N] other|another target B" (Relic Crush), subject "another target player" in a later sentence (`activation_clauses.stamp_distinct_target_player`; Cybernetica Datasmith). +4 MODELED, 0 lost, 2 changed. Tests `test_par285_sequential_another_target.py`.
  Milestone 5 (v974): controller's own sacrifice of a qualified pool: `edicts._SACRIFICE_CONTROLLER_POOL_RE` (edict_pool vocabulary; `exclude_source` for another / other than ~) and `MAY_COST_THEN_CLAUSE` sacrifice alt takes "<non-X|legendary|snow|tapped> <type>". +17 MODELED, 0 lost, 0 changed (full-pool diff vs 973). Tests `test_par285_sacrifice_qualified_pool.py` (2 behaviour tests fail with filter wiring disabled); `handler_row_order.txt` +1 row. Suite 24399 passed / 505 skipped.
  Milestone 6 (v975): search noun-phrase qualifier slot `quals` (legendary / nonlegendary / nonland|noncreature|nonartifact|nonenchantment) -> `card_query` `all_types`/`nonlegendary`/`without_type` (`search_control_attach._SEARCH_CRITERIA`, shared by every search row). +6 MODELED (Lifespinner, Thalia's Lancers, The Seriema, Time of Need, War of the Last Alliance, Woodland Bellower), 0 lost, 0 changed. Tests `test_par285_search_qualifier.py` (5 fail with slot disabled). Suite 24411 passed / 505 skipped. Left: Hero's Uncle (`team-up` not in SUBTYPES), Templar Knight (cost `tap 5 untapped attacking creatures named ~`), Grim Reminder (rider), The Champion (`that isn't a creature` tail), In Residence, Night Dealings (`mana value x` exact). `from <zone>` probe regex was too broad (775): re-probe per verb ("return ... from a graveyard") before building.
  Milestone 7 (v976): graveyard pick slots: multi-exile takes scope words ("exile 2 target cards from an opponent's graveyard", `_MULTI_EXILE_SCOPE_WORD`), multi-return takes "tapped", whole-graveyard exile takes a card type (`exile_target_graveyard.card_type`). +6 MODELED (5 newly covered: Deadeye Tracker, Lochmere Serpent, Necromancer's Covenant, Pull Through the Weft, Vengeful Regrowth; 1 authored: Crypt Incursion), 0 lost, 0 changed. Tests `test_par285_graveyard_multi_slots.py`. `from <zone>` left (v975 grid): single-card row lacks subtype/`noncreature artifact` words (Angel of Flight Alabaster, Salvaging Station mv<=1), `put ... onto the battlefield tapped under your control` (Demon of Dark Schemes), hand+graveyard exile (Identity Crisis, Thought Distortion, Worldfire: needs a hand-exile effect), `that was put there this turn` riders (Abyssal Harvester, Lobelia), `mana value x|less than ~'s power` exile bounds (Sequence Engine, Tamiyo, Nahiri, Narset, Arcane Proxy), Kenriths/Shadow of the Enemy/Kaervek/Nashi/Lara Croft (other clause open).
  Milestone 8 (v977): single-card graveyard pick subtype slot (`tap_return_zones._GRAVEYARD_SUBTYPE_SLOT`: "target <subtype> [type] card", "<A> or <B> [type] card" -> `TargetSpec.subtype` / `creature_filter.subtype_any`) in the return row and the reanimate row, which also reads "onto the battlefield tapped under your control"; graveyard target branch matches subtype via `has_subtype` (whole word, Changeling). +37 MODELED (33 newly covered, 4 authored), 0 lost, 0 changed. Tests `test_par285_graveyard_subtype_pick.py`. Solo-card grouping at v975 (122 solo P1-C cards by axis): with-quality vokabel 52 (diffuse: dynamic mv/power bounds ~13 across 7 quantities, `x target`, token `with <keyword>`), qualifier adjective 20 (diverse verb rows: `x target nonland`, `counter target nonblue spell`, `nonsnow land`, `noncreature artifact card`, `legendary permanent cards` mass return), with-quality slot 12, another/other 9, from-zone 8+2, tapped 7, named/shares-name 6. Left in graveyard row: `noncreature artifact card ... mv 1 or less` (Salvaging Station), "creature or land card" union, hand+graveyard returns (Kastral, Thran Temporal Gateway).
  Milestone 9 (v978): counted-target operand takes announced-X / any-number counts (`object_phrase._QUANTIFIER`/`_START`, `ObjectPhrase.count_selector` -> `choose_targets.count_selector`, cap `ANY_NUMBER_TARGET_CAP`), "to their owner's hand" pronoun rewrite, `where_x._rebind_announced_choose` (", where X is ..." on the `seq[choose_targets, for_each]` shape: Vile Requiem). Engine finding fixed: single-type target frames `artifact/enchantment/land/other_land/noncreature_artifact` ignored `creature_filter` (snow land, noncreature artifact offered wrongly, also for already-MODELED Crush/Sculptor of Winter/Earthcraft...): `apply_creature_filter=True` (audited: 25 cached cards, 9 distinct (kind, filter) dicts, all keys read; `combat.matches_object_filter` now also reads `without_type` as `without_card_type`, Rhino's Rampage; unknown filter keys are otherwise silently ignored by the reader). Tests `test_par285_x_target_count.py`. Grid at v977 (solo counts): graveyard union ~8, counter-nonX-spell 3-5, hand-put 37 (diverse: per-player "each player may put" ~8 needs engine, "any number of" count, multicolored), `x target` 40 -> claimed 16.
- **In progress:** (nothing)
- **Next step:** next solo-heavy slots: (a) qualifier adjective in verb rows (`x target <qual>` count: Dregs of Sorrow, Gridlock, Synod Artificer; `counter target nonblue/nonartifact spell`: Frazzle, Revolutionary Rebuff; `nonsnow land you control` Hallowed Ground; `nonwhite, nonblack` Seize the Soul), (b) dynamic mv bound `less than or equal to <count>` via `count_selector` dict (Sundering Archaic colours spent, Legacy's Allure, Grim Servant devotion). Older: sacrifice-family leftovers (each 1-2: Ravenous Vampire `if you don't` after qualified-cost antecedent, Reno and Rude / Vengeful Villagers `then you may sacrifice` after another clause, Dreadfeast Demon/Promise of Aclazotz hyphen `non-demon` cost phrase unreadable by `costs.parse_activation_cost`, Abjure/Ultimate Nullification additional-cost qualified sacrifice, Iron Man search-by-sacrificed-MV), then `from <zone>` rest (see M7 list) and `search ... legendary/nonland card` (search row takes only plain type words). Older: remaining sequential-another leftovers (each 1-2 cards: Rookie Mistake shared-duration `gets +0/+2 and another target creature gets -2/-0 until end of turn`, Arm the Cathars/Blue Dragon comma list, Trick Shot (`up to 1 other target creature token` elided damage conjunct, object_phrase seq not stampable), Serpentine Spike `a third target`, Withdraw (`unless its controller pays`), Friendly Rivalry/Graceful Takedown, Tandem Takedown), plus plural "other" groups (static multi-subtype anthems `other pegasi, unicorns, and horses you control get +1/+1`: 5 cards, 1 solo; parameterised keyword grants `other rats you control have toxic 1`/`ward {1}`: 5 solo, only ward/toxic engine-backed). Earlier note: remaining `another/other` group = plural/group forms ("other goblins and orcs you control get ...", "other modified creatures", "each other creature") and "another target X" after an earlier target (needs a distinct-from-earlier-target requirement flag: `TargetSpec.distinct_from_others` exists for fights; would unlock Hidden Strings, Toils, Tandem Takedown, Cybernetica Datasmith). Else qualifier adjective group (46: `nontoken/nonland/nonblack/legendary` slot in sacrifice/search/destroy rows) or `from <zone>` (29). Run `parser_probe blocked` first.
- **Decisions:** milestones commit one at a time (as for PAR-284); the orchestrator runs `--full-cache` only every fifth loop iteration, so the worker must not run it unless told to.
- **Baselines / artefacts:** v970->v971 coverage 25940 -> 25943; v969 vollpool scan 2026-11-18: `P1-C Objektfilter` 277/271/145; v975 scan: 234/228/113 (before M7); v969 covered 25935 -> v970 25940. Exports `backend/data/exports/offene-fragmente-2026-11-18-v969-vollpool-*`.
- **Known failures:** (none recorded)
- **Residue:** Ranked groups (277 sentences, class MOD): (1) `with <quality>` vokabel 106 (done part: X-bound; rest diffuse: keyword with, `base power`, `time counter`, `mana value` dynamic bounds, `greatest/lowest`); (2) qualifier adjective 46; (3) `another/other` 41; (4) `from <zone>` slot 29 + vokabel 7; (5) `with <quality>` slot 22; (6) named/shares name 11; (7) tapped 7; (8) controller scope 4; attacking 3. Open X-shaped: Ent-Draught Basin (`power x` exact), mass `toughness/mana value x or less` (Zero Point Ballad, Day of Black Sun, Droning Bureaucrats). Carried from PAR-284: Duskana (`base power and toughness 2/2`), Cid (anthem head union). Aryel parsed; X-from-tap-cost execution not bench-verified.
