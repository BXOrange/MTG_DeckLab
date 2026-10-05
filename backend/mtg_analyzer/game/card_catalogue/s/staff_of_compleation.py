from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _staff_of_compleation() -> list[AbilitySpec]:
    """{T}, Pay 1 life: Destroy target permanent you own.
    {T}, Pay 2 life: Add one mana of any color.
    {T}, Pay 3 life: Proliferate.
    {T}, Pay 4 life: Draw a card.
    {5}: Untap this artifact.

    — PLAY-ALL (Abzan Armor). The any-colour mana ability is derived from the text; proliferate, draw and untap are the
    parser's. The destroy ability targets a permanent *you own* (``permanent_you_own``, the owner-scoped frame).
    """
    return [
        AbilitySpec(
            "activated", [EffectSpec("destroy", {"target_kind": "permanent_you_own"})],
            cost={"text": "{T}, Pay 1 life"},
        ),
        AbilitySpec("activated", [EffectSpec("proliferate", {})], cost={"text": "{T}, Pay 3 life"}),
        AbilitySpec("activated", [EffectSpec("draw", {"count": 1})], cost={"text": "{T}, Pay 4 life"}),
        AbilitySpec("activated", [EffectSpec("tap", {"target_kind": None, "untap": True})], cost={"text": "{5}"}),
    ]


register("Staff of Compleation", _staff_of_compleation)
