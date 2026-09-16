from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _squee_the_immortal() -> list[AbilitySpec]:
    """Squee, the Immortal (Legendary Creature — Goblin, {1}{R}{R})

    "You may cast this card from your graveyard or from exile."

    A bare self-referential zone permission — `SelfGraveyardOrExileCast
    PermissionEffect` (MEC-40), read directly off this object's own
    ``static_effects`` regardless of which of the two zones it's
    currently sitting in.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("self_graveyard_or_exile_cast_permission", {})],
        ),
    ]


register("Squee, the Immortal", _squee_the_immortal)
