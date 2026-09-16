from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deadly_brew() -> list[AbilitySpec]:
    """Each player sacrifices a creature or planeswalker of their choice. If
    you sacrificed a permanent this way, you may return another permanent
    card from your graveyard to your hand.

    Documented simplification: the "if you sacrificed a permanent this way"
    gate and the "another" narrowing are dropped — the return is offered as
    an optional graveyard-permanent pick."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("sacrifice", {
                    "selector": "each_player", "what": "creature_or_planeswalker", "count": 1,
                }),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_permanent", "destination": "hand", "optional": True,
                }),
            ],
        ),
    ]


register("Deadly Brew", _deadly_brew)
