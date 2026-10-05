# Rules Wiki — LLM navigation layer for the Comprehensive Rules

The Magic Comprehensive Rules (`MagicCompRules 20260807.txt`, ~975 KB) are too large to load
whole. This directory is a **navigation layer**: it maps every rule number and
glossary term to a line in that source file so an agent can read exactly the
passage it needs. **The rules text is not copied here** — the source `.txt`
stays the single source of truth.

## Files

| File | Use it to |
| --- | --- |
| [RULES_WIKI.md](RULES_WIKI.md) | Browse parts → sections; get a section's line. |
| [glossary_index.md](glossary_index.md) | Look up a defined term → line + rule. |
| `rule_line_index.json` | Machine-readable rule#/subrule#/term → line. |
| `build_wiki.py` | Regenerate everything after a rules update. |

## How an agent uses it

1. Have a `RULE <n>` reference (e.g. from code)? Look it up:
   - section like `613` → find its line in `RULES_WIKI.md`.
   - subrule like `613.7` → `rule_line_index.json` → `subrules["613.7"]`.
2. `Read("Reference/MagicCompRules 20260807.txt", offset=<line>, limit=~40)` — read just that rule.
3. Unknown term? `glossary_index.md` gives its line **and** the rule that defines it.

## Engine concept → rules map

Bridges this repo's subsystems to the CR sections they implement
(mirrors CLAUDE.md's "Where to look first").

| Subsystem | Rules | Code |
| --- | --- | --- |
| Turn / phase / step loop | 500 General, 501 Beginning Phase, 502 Untap Step, 503 Upkeep Step, 504 Draw Step, 505 Main Phase, 506 Combat Phase, 512 Ending Phase, 513 End Step, 514 Cleanup Step | `game/game_engine.py` |
| Combat & combat keywords | 506 Combat Phase, 507 Beginning of Combat Step, 508 Declare Attackers Step, 509 Declare Blockers Step, 510 Combat Damage Step, 511 End of Combat Step, 702 Keyword Abilities | `game/combat.py, game/game_engine.py (_step_combat_damage)` |
| Casting spells / the stack | 601 Casting Spells, 608 Resolving Spells and Abilities, 112 Spells, 405 Stack | `game/rules_engine.py, services/game_session.py` |
| Activated abilities & costs | 602 Activating Activated Abilities, 118 Costs, 606 Loyalty Abilities | `game/costs.py, game/game_engine.py (activate_ability)` |
| Triggered abilities | 603 Handling Triggered Abilities | `game/effects/core.py, game/binding/core.py` |
| Static abilities / layers (P/T, anthems) | 604 Handling Static Abilities, 611 Continuous Effects, 613 Interaction of Continuous Effects | `game/continuous.py, models/game_object.py` |
| Replacement & prevention effects | 614 Replacement Effects, 615 Prevention Effects, 616 Interaction of Replacement and/or Prevention Effects | `game/effects/core.py` |
| Mana | 106 Mana, 107 Numbers and Symbols, 202 Mana Cost and Color, 605 Mana Abilities | `game/mana_abilities.py, models/mana_cost.py, models/mana_pool.py` |
| Targeting | 115 Targets, 601 Casting Spells | `game/targeting.py` |
| State-based actions | 704 State-Based Actions | `game/rules_engine.py (SBAs)` |
| Damage / life | 119 Life, 120 Damage | `game/rules_engine.py` |
| Counters | 122 Counters | `game/rules_engine.py` |
| Zones | 400 General, 401 Library, 402 Hand, 403 Battlefield, 404 Graveyard, 405 Stack, 406 Exile | `models/game_state.py` |
| Keyword actions & abilities | 701 Keyword Actions, 702 Keyword Abilities | `game/combat.py, game/effects/core.py` |
| Commander | 903 Commander | `services/game_session.py` |
| Mulligan / starting the game | 103 Starting the Game | `game/game_engine.py` |

## Regenerating

Drop the newer `MagicCompRules <date>.txt` into `Reference/` and run:

```bash
python3 docs/Reference/rules_wiki/build_wiki.py
```

It picks the newest `MagicCompRules*.txt` automatically. The concept map at
the top of `build_wiki.py` is hand-maintained — update it when subsystems move.
