from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _insult_injury() -> list[AbilitySpec]:
    """Damage can't be prevented this turn. If a source you control would
    deal damage this turn, it deals double that damage instead.

    — MEC-30's one real new mechanism: `disable_damage_prevention` flips a
    turn-scoped `GameState` flag that `RulesEngine._run_replacement_loop`
    checks generically against every replacement's new `prevents_damage`
    marker; `grant_damage_multiplier_this_turn` is the spell-cast sibling
    of the standing `double_damage` replacement (Furnace of Rath-shaped),
    filed on the caster's own `player_effects` since a resolved sorcery has
    no permanent to attach a standing shield to. Unscoped by recipient —
    "a source you control" doubles damage to *anyone*, no `to_opponent_
    only`, unlike Isengard Unleashed's own qualified sibling.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("disable_damage_prevention", {}),
                EffectSpec("grant_damage_multiplier_this_turn", {"multiplier": 2}),
            ],
        ),
    ]


register("Insult // Injury", _insult_injury)
