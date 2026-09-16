from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ifnir_deadlands() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}, Pay 1 life: Add {B}.
    {2}{B}{B}, {T}, Sacrifice a Desert: Put two -1/-1 counters on target
    creature an opponent controls. Activate only as a sorcery.

    Both mana abilities fold in from `mana_abilities_for` (independent of
    registration). Authored: the sorcery-speed sacrifice ability — the
    cost's ``Sacrifice a Desert`` subtype filter is already understood by
    `game/costs.parse_activation_cost`; the effect is a plain targeted
    ``add_counters`` (``creature_you_dont_control``, RULE 115).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {
                "count": 2, "kind": "-1/-1", "target_kind": "creature_you_dont_control",
            })],
            cost={"text": "{2}{B}{B}, {T}, Sacrifice a Desert", "sorcery_speed_only": True},
        ),
    ]


register("Ifnir Deadlands", _ifnir_deadlands)
