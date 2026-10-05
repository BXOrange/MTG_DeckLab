from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ferrafor_young_yew() -> list[AbilitySpec]:
    """When Ferrafor enters, create a number of 1/1 green Saproling creature
    tokens equal to the number of counters among creatures target player
    controls.
    {T}: Double the number of each kind of counter on target creature.

    Authored wholesale: the ETB trigger via new
    `CreateTokensPerCounterAmongTargetPlayerCreaturesEffect` (targets a
    player, counts every counter on that player's creatures), and the tap
    ability via new reusable `DoubleCountersOnTargetEffect` (RULE 701.19).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {"name": "n", "amount": {
                "kind": "counters_among_creatures", "of": "target",
            }, "effects": [{"type": "create_token", "params": {
                "count": "$n", "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Saproling"], "token_name": "Saproling",
            }}]})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("double_counters_on_target", {"target_kind": "creature"})],
            cost={"text": "{T}"},
        ),
    ]


register("Ferrafor, Young Yew", _ferrafor_young_yew)
