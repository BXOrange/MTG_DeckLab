from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nesting_grounds() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {1}, {T}: Move a counter from target permanent you control onto a
    second target permanent. Activate only as a sorcery.

    The mana ability folds in from `mana_abilities_for`. Authored: the
    sorcery-speed move-a-counter ability (new `MoveCountersEffect` —
    ``permanent_you_control`` source + a distinct second ``permanent``
    target, RULE 122.3).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("move_counters", {})],
            cost={"text": "{1}, {T}", "sorcery_speed_only": True},
        ),
    ]


register("Nesting Grounds", _nesting_grounds)
