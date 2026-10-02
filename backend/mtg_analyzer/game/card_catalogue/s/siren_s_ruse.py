from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sirens_ruse() -> list[AbilitySpec]:
    """Exile target creature you control, then return that card to the
    battlefield under its owner's control. If a Pirate was exiled this way,
    draw a card.

    — PLAY-ALL Step 2 (Wick Snail Boom). Ephemerate's `blink` on a
    ``creature_you_control`` target, then a `draw` gated by the flat effect
    condition ``previous_target_has_subtype: Pirate`` (read off the creature
    the blink just handled, the same "that card" referent).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("blink", {"target_kind": "creature_you_control"}),
                EffectSpec("draw", {"count": 1}, condition={"previous_target_has_subtype": "Pirate"}),
            ],
        )
    ]


register("Siren's Ruse", _sirens_ruse)
