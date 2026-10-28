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
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-215 · Referenced-object amounts and mana-value comparisons

- **Started / last update:** 2026-10-28 / 2026-10-28 (milestone 2)
- **Goal of this run:** close the ticket: `equal to its / that card's mana value / power / toughness`, `the damage dealt / prevented this way`, `the number of <counted objects>`, `with mana value x or less / less than or equal to <amount>` as operands of existing life, damage, draw, token, P/T and filter effects (`effect_amounts.py`). Scan sizes 384+316 touched / 243+143 only (v792).
- **Done (built + tested):** (A) referent amounts: `segmenter._referent_characteristic_specs` accepts `that card's` / `that spell's`, recipient-first damage (`deals damage to that player equal to ...`) and `up to one target`; new `REVEALED` referent (clause_reading.py; `produces()` yields it after `reveal_top`/`put_revealed_card`, a lone `inspect_cards` reveal, or a one-card `exile_top_of_library`, carried by the sequencing loop); `reveal_top_take` row (draw_discard_cast.py: "reveal the top card of your library and put it into your hand"); `inspection._REVEALED_AMOUNT_FOLLOW_UP` exempts "equal to its/that card's <char>" from the dangling-pronoun guard. "that spell's" binds only after a counter (COUNTERED referent); "that card's" refuses a made token (CREATED) or no picked card. (C) mana-value bounds: counter/copy spell filters `with mana value N or less/greater` (subgrammars SPELL_TARGET, `targeting._spell_matches_filter` min_mana_value, `CounterSpellEffect.max_/min_mana_value`, registry), `gain control of target X with mana value x or less` takes the announced X (Dominate). Fixes found on the way: `_peel_condition` kept only the outer gate over an inner spec's own condition (now `all`); object_phrase refuses "attach it to ~" (inverted direction, Thieving Skydiver). PARSER_VERSION 794 + lock + history; handler_row_order.txt gets `reveal_top_take`; tests/test_par215_referenced_amounts.py (23); test_par71 Draining Whelk expectation flipped to modeled. MILESTONE 2 (v795, uncommitted until the orchestrator commits): (B) `damage_equal_to_power` role recipients (`recipient`: dealer_controller / ability_controller / source; selector `each_other_creature`; `characteristic` power|toughness; rows `damage_equal_to_power_*_role`, costs_mana_limits.py). (F) `GameContext.damage_dealt_this_way` (zeroed per resolving stack item in casting_mixin), `this_way` tally + `_DAMAGE_THIS_WAY_RE` amounts ("equal to the (excess) damage dealt this way"), gate "excess damage was dealt this way" (static_handlers amount_compare). (D) `segmenter._relative_player_amount` (single target / step-trigger player, `of: target|active_player`, STEP_BEGIN-gated via `event_player_events`), `quantifier_scope.per_member_amount_specs` widened ("that player controls", "twice the number of", "for each"). (E) mass "with mana value equal to / <= the number of <counters> on ~" (`_MANA_VALUE_AMOUNT_RE` -> where-x bind), targeted count bound `TargetSpec.max_mana_value={"count_selector":..}` (`_mana_value_count_bound_specs`, `targeting.legal_targets`); BUG FIX found on the way: object_phrase `for_each` over a group dropped the singular body target bounds (Dauntless Dismantler, Pernicious Deed, Vicious Rivalry, Swift Demise destroyed every member) -> `_fold_target_bounds_into_group`, `exact_mana_value` filter key, `_substitute_x` reaches a loop selector filter. Tests: test_par215_{damage_recipients,damage_this_way,relative_player_counts,mana_value_bounds}.py.
- **In progress:** nothing; milestone 2 (axes B, F, D, E) committed at v795 — default tier 17073 passed / 487 skipped, --full-cache 17559 passed / 1 skipped (orchestrator-verified). find-fragments v795: open 9118 cards, 13330 fragments, covered 22830. Spec diff v794→v795: +54 modeled, 0 lost, 4 changed (group-bound fixes).
- **Next step:** residue axes only (below); nothing mandatory left in B/D/E/F beyond the listed residue. Commit, then pick residue items by find-fragments rank.
- **Decisions:** referent chosen from the earlier clause's producer, never from the noun alone; wrong-but-MODELED candidates declined (Deekah token-sizing, Thieving Skydiver). `x or less` on a spell filter refused (announced X as a ceiling not modelled). Did not touch `Referent` for random-hand reveals (Planeswalker's Fury family).
- **Baselines / artefacts:** PARSER_VERSION 794 -> 795. Spec dumps in the session scratchpad (before.json, after3.json = v794 baseline, afterF.json = v795): +54 newly modeled, 0 lost, 4 changed. Fragment scans: v793 9193 open / v794 9170 open (see report for v795).
- **Known failures:** none from this ticket.
- **Residue:** (B) multi-dealer "up to 2 target creatures you control each deal damage equal to their power to ..." (Allies at Last, Band Together, Common Goal, Coordinated Clobbering, Terrific Team-Up), "another target creature, planeswalker, or battle" / "that permanent" / "target creature with flying" recipients, "assigns combat damage equal to its toughness", spell-power dealers (Essence Backlash), bolg/referent-power + excess bodies. (F) "damage prevented this way" (Acolyte's Reward, Divine Deflection, Refraction Trap, Chant of Vitu-Ghazi: need a prevention-shield tally), "creatures dealt damage this way" groups (Aurelia's Fury, Aggravate, Huatli), bodies with no X support ("amass/discover/look at the top x ... where x is that excess damage", "that many tapped Treasure"). (D) "for each <creature group> they control" per-player (group phrase routes to object iteration), "N minus the number of cards in their hand" (Rackling, Wheel of Torture, Storm World), explicit second target in the phrase, event-player counts under damage/attack triggers (Sword of War and Peace, Emberwilde Captain: `event_player` is the SPELL_CAST player, the gate refuses), "for each X target opponent controls" bodies with no player target (Starlight, Divine Congregation). (E) per-candidate bounds relative to the target's controller (Drown in the Loch, Beguiler of Wills power bound), "mana value less than the revealed/sacrificed card's" and "1 plus the sacrificed permanent's mana value" search filters, Wave of Terror/Corrosion/The Moment/Sphere of Annihilation still blocked by other clauses. Plus the milestone-1 residue: "base power and toughness each equal to its mana value", "pay life equal to its mana value" alt-costs, literal-bound filters in graveyard-return/dig/"from among them" rows (~40 clauses).
