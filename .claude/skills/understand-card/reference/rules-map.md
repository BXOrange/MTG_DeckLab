# Oracle-text idiom → CR section → where it's modeled

The `understand_card.py` term scan maps single defined words to rules. This
table maps the *idioms* it can't — the recurring clause shapes — to the CR
section that governs them and the file that models them. Use it to answer
"which rule does this phrasing invoke, and is the primitive already there".

Read the CR passage with `understand_card.py term "<word>"` or
`engine_bench.py rule <n>`; confirm a primitive exists with
`engine_bench.py primitives '<shape>'`.

## Triggers (RULE 603)

| Idiom | Rule | Modeled in |
| --- | --- | --- |
| "When/Whenever/At …" (recognising the condition) | 603.1–603.2 | `parser/oracle/segmenter.py` (`_TRIGGER_RE`, `_trigger_condition`) |
| "When ~ enters" / "dies" / "attacks" / "blocks" | 603.2, 603.3 | segmenter trigger conditions → `game/binding/core.py` `_trigger_condition` |
| "Whenever you gain life / cast / draw" (player events) | 603.2 | segmenter `_PLAYER_TRIGGER_CONDITIONS`; engine `EventType.*` in `game/rules_engine.py` |
| "At the beginning of the next …, …" (delayed) | 603.7 | `effects.CreateDelayedTriggerEffect`, `GameState.delayed_triggers` |
| "When you do, …" (reflexive) | 603.2e | `pay_cost_then` spec / `game/effects/` |
| Intervening "if" clause | 603.4 | trigger `condition` param |

## Static abilities & continuous effects (RULE 604, 611, 613)

| Idiom | Rule | Modeled in |
| --- | --- | --- |
| "Creatures you control get +1/+1" (anthem/lord) | 613 layer 7c | `parser/oracle/catalogue/static_handlers.py` → `game/continuous.py` |
| "~ can't be blocked …" / "attacks each combat if able" | 509, 508.1 | `game/combat.py` restriction/requirement family |
| "As long as …, …" (conditional static) | 613.6 | `game/static_conditions.py`, static `active_if` param |
| "Until end of turn" / "until your next turn" | 611 | `game/durations.py` (`temp_*` path for EOT), `effects.GrantUntilEffect` |
| "has \"<ability>\"" (granted ability) | 613 layer 6 | catalogue quoted-ability grants; `game/card_catalogue/` for singletons |
| type-/color-changing ("is a 1/1 Insect in addition") | 613 layers 4, 7b | `game/continuous.py`; often UNCLAIMED → `game/card_catalogue/` |

## Replacement & prevention (RULE 614, 615, 616)

| Idiom | Rule | Modeled in |
| --- | --- | --- |
| "If ~ would die, exile it instead" | 614 | `ReplacementEffect` (`game/effects/replacements.py`); **no parser grammar** → `game/card_catalogue/` |
| "enters with N +1/+1 counters" / "enters tapped" | 614.1 | catalogue `enters_tapped` / enters-with-counters (oracle-derived) |
| "Prevent all damage that would be dealt to …" | 615 | `game/effects/` prevention shields |
| "If you would draw … instead …" | 614 | replacement — hand-author |

## Activated abilities & costs (RULE 602, 118, 606)

| Idiom | Rule | Modeled in |
| --- | --- | --- |
| "<cost>: <effect>" | 602 | `parser/oracle/catalogue/handlers.py`, `game/costs.py` |
| "{T}, Sacrifice ~: …" / "Pay N life:" additional costs | 118 | `game/costs.py` cost parser |
| "[+1] / [−2] / [−X]" loyalty | 606 | `game/game_engine.py` `activate_ability` |
| "Activate only as a sorcery" / "only once each turn" | 602.5 | segmenter activation markers |

## Keyword actions (RULE 701) — every one has an engine primitive (PAR-29 closed)

Common: Destroy 701.8, Exile 701.20, Sacrifice 701.21, Tap/Untap 701.22,
Counter 701.6, Create 701.7, Draw 701.24, Discard 701.9, Mill 701.17,
Search 701.19, Scry 701.20, Fight 701.14, Proliferate 701.29,
Cascade 702.85, Explore 701.44. Primitive: `game/effects/` (grep the
effect-type string); parser bodies: `parser/oracle/catalogue/handlers.py`.

## Combat (RULE 506–511, 702)

| Idiom | Rule | Modeled in |
| --- | --- | --- |
| Evasion / combat keywords (flying, menace, trample, landwalk, …) | 702 | `game/combat.py` keyword recognition + blocking legality |
| "can't be blocked by more than one creature" / multi-block | 509.1c, 508.4 | `game/combat.py` restriction/requirement family |
| first strike / double strike damage steps | 510.5 | `game/game_engine.py` `_step_combat_damage` |
| goad | 701.38 | `game/combat.py` |

## Zones, targeting, SBAs

| Idiom | Rule | Modeled in |
| --- | --- | --- |
| "target creature you don't control" (legal-target computation) | 115, 601.2c | `game/targeting.py` |
| "N or more" / "up to N" / "each" target counts | 115.1, 601.2c | `game/targeting.py` `TargetSpec.count*` |
| "return ~ from your graveyard to the battlefield" | 404, 400.7 | `game/rules/*_mixin.py`; `GameObject.reset_as_new_object` (RULE 400.7) |
| "the number of X in your graveyard" (dynamic count) | 107.3 | count selectors in `game/effects/` / `targeting.py`; often UNCLAIMED |
| state-based: 0 toughness, lethal damage, legend rule | 704 | `game/rules_engine.py` `check_state_based_actions` |

## When a clause comes back UNCLAIMED

1. `understand_card.py clause "<the normalized clause>"` — read its governing
   rules and the isolated verdict.
2. `understand_card.py rulings "<card>"` — a ruling flagged "overlaps an
   UNCLAIMED clause" is usually the plain-English spec for exactly this clause
   (edge cases, "only once each turn", what counts, what doesn't trigger).
   Read it before designing the handler/effect — it tells you the corners the
   implementation has to get right.
3. `parser_probe.py blocked '<regex>'` — is there a cluster, or is it a
   singleton?
4. Cluster with an existing near-shape → widen a handler (`extend-parser`).
   Singleton, or a replacement effect, or a real conditional trigger predicate
   → `hand-author-card`.
5. No primitive at all for the effect → `engine_bench.py primitives` to be
   sure, then it's a `MEC`/`ENG` ticket.

## Validating an already-MODELED card against its rulings

`understand_card.py check "<card>" --rulings` lists the rulings that describe
timing / layer / counting behaviour. For each one, reproduce the described
board with `engine_bench.py play` / `combat` and confirm the outcome matches
the ruling verbatim — these are the cases that bind and parse cleanly but
still resolve wrong (layer order, last-known-information, "only once",
intervening-if, replacement vs. trigger).
