from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _isengard_unleashed() -> list[AbilitySpec]:
    """Damage can't be prevented this turn. If a source you control would
    deal damage this turn to an opponent or a permanent an opponent
    controls, it deals triple that damage instead.
    Flashback {4}{R}{R}{R}

    — Flashback is the ordinary keyword fold-in. Same shape as Insult //
    Injury, ``multiplier=3`` and ``to_opponent_only=True`` for the
    qualified recipient side.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("disable_damage_prevention", {}),
                EffectSpec("grant_damage_multiplier_this_turn", {
                    "multiplier": 3, "to_opponent_only": True,
                }),
            ],
        ),
    ]


register("Isengard Unleashed", _isengard_unleashed)
