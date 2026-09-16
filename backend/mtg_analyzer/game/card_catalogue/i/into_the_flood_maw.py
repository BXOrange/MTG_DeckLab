from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _into_the_flood_maw() -> list[AbilitySpec]:
    """Gift a tapped Fish (You may promise an opponent a gift as you cast
    this spell. If you do, they create a tapped 1/1 blue Fish creature
    token before its other effects.)
    Return target creature an opponent controls to its owner's hand. If
    the gift was promised, instead return target nonland permanent an
    opponent controls to its owner's hand.

    — MEC-12 (cEDH Kinnan). **Documented simplification**: the Gift
    mechanic (RULE-adjacent WOE ability word — a cast-time "promise a
    gift" branch with no engine primitive anywhere yet) is dropped
    entirely; this always resolves as the un-gifted base mode ("return
    target creature an opponent controls to its owner's hand"), never
    offering the opponent a Fish or the "any nonland permanent" upgrade.
    Building Gift generally is real, standalone engine work — a genuinely
    new interactive cast-time choice threaded through casting/targeting —
    not something to fold into one card's own entry.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {"target_kind": "creature_you_dont_control"})],
        ),
    ]


register("Into the Flood Maw", _into_the_flood_maw)
