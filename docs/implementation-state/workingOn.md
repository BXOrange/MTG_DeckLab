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
- **Done (M3, v989):** "whenever that creature <attacks (the monarch) | becomes blocked | deals combat damage to a player (or planeswalker)> this turn" after a clause that chose the creature (`THAT_CREATURE_SUBJECT_RE`; `aim_at_linked_creature` points the untargeted pump / blocker count at the firing creature; `TurnScopedTrigger.ends_when_object_moves`, RULE 400.7). +3 (Okoye Mighty and Adored, Barreling Attack, Hunter's Insight), +1 already authored (The Inner Light), 0 lost, 0 changed. Tests: `test_par286_that_creature_heads.py`.
- **Done (M4, v990):** cost "Put a card an opponent owns from exile into that player's graveyard" (`ActivationCost.put_opponent_exile_to_graveyard`, pool `_opponent_exile_pool`; the activator picks the card: legal-action `opponent_exile_cost`, wire `opponent_exile_choices` -> `hand_card_choices`, validated by `_resolve_pool_cost`; the board UI picker is not built, so the board still auto-picks the first). +3 (Cryptic Cruiser, Oracle of Dust, Void Attendant), 0 lost, 0 changed. Tests: `test_par286_opponent_exile_cost.py`.
- **Done (M5, v991):** "whenever an instant or sorcery spell | a spell you control deals damage [to an opponent]" (`object_trigger_head._SPELL_SOURCE_SUBJECT` + the binder's `requires_source_instant_or_sorcery`; DAMAGE already carried `source_is_instant_or_sorcery`). +3 (Blaze Commando, Satyr Firedancer, Flame Channeler), 0 authored, 0 lost, 0 changed. Wiring-off: 3 near-miss tests fail. Tests: `test_par286_spell_damage_heads.py`.
- **Done (M6, v992):** bundle of three head clusters on existing events: "whenever you gain or lose life during your turn" (`LIFE_GAINED`+`LIFE_LOST` share `limit_group`), "enchanted / fortified <permanent> becomes tapped" (+ attached-subject "that creature's / its controller" bodies via `shared.match_clause_reading`), "whenever a permanent you control transforms [into <phrase>]" (`_parse_transforms_head`, filter read on the live new face), "1 or more <phrase> become tapped" batch (`TAPPED` in `BATCHED_EVENT_TYPES`; attack declaration and mass `TapEffect` run in `simultaneous()`). +11 newly covered (Cult of the Waxing Moon, Darksteel Garrison, Deeproot Pilgrimage, Impending Doom, Insolence, Lust for War, Moonstone Harbinger, Norn's Inquisitor, Psychic Venom, Relic Putrescence, Wax-Wane Witness), 0 authored, 0 lost, 0 changed. Tests: `test_par286_tap_life_transform_heads.py`.
- **Done (M7, v993):** "when you discard this card" (+ Bartered Cow's "when ~ dies and when you discard this card" split; `line_self_discard`), "whenever a creature [you control] dealt damage this way dies this turn" (`create_turn_trigger.damaged_this_way` -> `TurnScopedTrigger.dealt_damage_visits`, RULE 603.7c/400.7), reflexive payoff "target X and it gains ..." pronoun exemption (Sigil of Myrkul). +6 newly covered (Bartered Cow, Ghired's Belligerence, Reckless Blaze, Sigil of Myrkul, Skeletonize, Titanbones), +1 authored card also MODELED now (Edgar's Awakening), 0 lost, 0 changed. Wiring-off: 3-5 tests fail per change. Tests: `test_par286_discard_damaged_dies_heads.py`.
- **Done (M8, v994):** reflexive "When you do" payoffs naming the antecedent's object: `ReflexiveTriggerEffect.carry_referent` ("created") -> `enqueue_reflexive_trigger(carried_objects)` -> `CarriedAntecedentEffect` seeds `previous_targets` (zone visit kept, RULE 400.7); `AmassEffect` lists the Army it found; `_action_when_you_do` claims create_token / amass / return_from_graveyard antecedents with an "it" / "the amassed Army's power" payoff, and a targeted return / attach antecedent. +4 newly covered (Back for More, Foray of Orcs, Novel Nunchaku, Windmill Slam), 0 authored, 0 lost, 0 changed. Wiring-off: seed off 5 tests fail, amass listing off 1. Tests: `test_par286_carried_antecedent.py`.
- **Done (M9, v995):** (a) LKI for a carried antecedent: `CarriedAntecedentEffect` seeds the departed visit's `zone_visit_sources` snapshot (RULE 608.2h / 113.7a), so Windmill Slam / Foray of Orcs deal the last-known power after the token / Army left; Back for More's fight with a gone creature still does nothing (RULE 701.14b). (b) Row `any_number_when_you_do` ("<tap|sacrifice|discard|exile> any number of / one or more <pool>. When you do, <payoff with that many | that much | -X/-X where X is the number ... this way>") over MEC-103's `choose_objects.then_that_many.trigger`; `target_count` binds too. +4 newly covered (Miasma Demon, Specter of Mortality, Swashbuckler Extraordinaire, Yotia Declares War), +1 authored also MODELED (Loamcrafter Faun, its spec executed), 0 lost, 0 changed. Wiring-off: handler off 11 tests fail, `target_count` key off 4 fail, LKI seed off 2 fail. Skipped: Resplendent Marshal (payoff filter "shares a creature type with the exiled card"). Known: the trigger-level "you may" asks before the pick. Tests: `test_par286_picked_count_payoff.py`, `test_par286_carried_antecedent.py`.
- **Done (M10, v996):** class-(i) bundle. Keyword events the engine now fires (`EVOLVES`, `CONNIVES` as the discard's `then_specs` tail / at once without a hand, `BECAME_SADDLED`; `RENOWNED` gained `controller_id` / `object_types`) with heads in `object_trigger_head`; "you play a card" (`LAND_PLAYED` + `SPELL_CAST`) and "play a land from exile or cast a spell from exile"; state triggers "when an opponent controls a creature with power N+ / has N or less life / a player has no cards in hand, if ~ is an enchantment, it becomes ..." (trigger-time `active_if`, new `any_player_cards_in_hand_at_most`) and "an opponent plays a nonbasic land"; tap-N cost "white and/or blue" / "attacking" / "named ~" / "Tapped four" (`anycolor:` / `attacking` / `named:~` words; `_tap_others_pool` passes the source); first-name subject of a comma-less legendary; die heads (`dice_rolled_this_turn`, natural 20, "a 6 is rolled on a 6-sided die"). Results in the report.
- **Done (M11, v997):** linked "that creature" heads, delayed-step heads, qualified cast / counter heads (19 cards) + 7 claimed incidentally (Blitz of the Thunder-Raptor, Bouncer's Beatdown, Combustion Technique, Magistrate's Veto, Necrotic Wound, Spoils of the Hunt, Temple Thief; executed on the real engine with near misses) = +26 newly covered, +2 authored also MODELED (Baral, Final Fortune), 1 lost (Careful Consideration: a wrong earlier claim, see below). Fail-closed guard in `bound_for_each_amount` (a "this way" amount over its own producer; Foggy Swamp Visions stays authored-only, fixes `test_par175_clause_linkage`). Second guard: `splits_inside_gated_sentence` no longer exempts a gated "instead" sentence, so a connector cut cannot gate only the first clause (Kamahl's Sledge and Careful Consideration stay unclaimed; the full-pool diff shows only those two change). Tests: `test_par286_linked_delayed_cast_heads.py`.
- **In progress:** (nothing)
- **Next step:** orchestrator: decide the Kamahl's Sledge fix, commit M11, close PAR-286 (move the singleton rows to singletons.md, file the proposed MEC lines).
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration. A head is only real if the trigger fires in the engine: tests drive the real event. "outlast" payoffs (Herald of Anafenza) are NOT claimed: the engine binds no outlast ability.
- **Baselines / artefacts:** v997: P1-D 293 / 611 / 96 (`...-v997-vollpool-*`); v992: P1-D 356 / 708 / 145; v990: P1-D 367 / 718 / 154 (files `...-v990-vollpool-*`); v986: P1-D 383 sentences / 736 cards touched / 169 solo (backlog v912 scan: 383 / 757 / 161). Scan files in `backend/data/exports/offene-fragmente-2026-11-19-v986-vollpool-*`.
- **Known failures:** (none recorded)
- **Residue:** v997 P1-D solo 96: (i) 2 (`pay X {E}` cost), (ii) 66 singleton rows, (iii) 1 (Emrakul's Evangel, MEC-145), (iv) 27 = 20 Un-set / playtest + 7 blocked by a missing primitive (plot, outlast, enlist, saga final-chapter event, regenerates-this-way: 5 proposed MEC lines). Final classification with paste-ready rows: `/private/tmp/claude-501/-Users-berndzacharias-Repositories-MTG-DeckLab/75f15a8a-77d2-4ee9-830c-6920de63b257/scratchpad/par286-closure-final.md`.
