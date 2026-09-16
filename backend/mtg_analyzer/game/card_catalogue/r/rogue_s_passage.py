from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rogues_passage() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {4}, {T}: Target creature can't be blocked this turn.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("unblockable", {"target_kind": "creature"})],
            cost={"mana": "{4}", "taps_self": True},
        )
    ]


register("Rogue's Passage", _rogues_passage)
