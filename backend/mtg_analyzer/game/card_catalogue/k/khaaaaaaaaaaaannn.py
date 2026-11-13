from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Khaaaaaaaaaaaannn! deals "twice X" damage.
KHAN_DAMAGE_PER_X = 2


def _khaaaaaaaaaaaannn() -> list[AbilitySpec]:
    """Khaaaaaaaaaaaannn! deals twice X damage to target creature. If that creature would die this turn, exile it instead.

    RULE 614.1a: the "would die" half is the turn-long die-to-exile
    replacement armed on the same target (``grant_die_to_exile_this_turn``,
    the Smite the Deathless idiom); "twice X" is ``x_multiplier``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"x_multiplier": KHAN_DAMAGE_PER_X, "target_kind": "creature"}),
                EffectSpec("grant_die_to_exile_this_turn", {}),
            ],
        ),
    ]


register("Khaaaaaaaaaaaannn!", _khaaaaaaaaaaaannn)
