from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _access_tunnel() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {3}, {T}: Target creature with power 3 or less can't be blocked this
    turn.

    (The mana ability is bound automatically off the printed "{T}: Add
    {C}." text — `game/mana_abilities.py` — so only the second ability
    needs authoring here.)
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": {"max_power": 3}})],
            cost={"mana": "{3}", "taps_self": True},
        ),
    ]


register("Access Tunnel", _access_tunnel)
