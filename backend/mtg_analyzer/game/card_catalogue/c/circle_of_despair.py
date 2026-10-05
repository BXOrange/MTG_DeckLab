from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _circle_of_despair() -> list[AbilitySpec]:
    """{1}, Sacrifice a creature: The next time a source of your choice
    would deal damage to any target this turn, prevent that damage.

    — ``target_kind="any"`` routes the shield's recipient through ordinary
    RULE 115 targeting instead of this effect's own controller — the
    already-designed "any target" branch `RequestPreventDamageSourceEffect`
    was built with (see its docstring), first actually used here.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "{1}, Sacrifice a creature"},
        ),
    ]


register("Circle of Despair", _circle_of_despair)
