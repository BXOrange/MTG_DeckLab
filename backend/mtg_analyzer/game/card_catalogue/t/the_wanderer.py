from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_wanderer() -> list[AbilitySpec]:
    """Prevent all noncombat damage that would be dealt to you and other permanents you control.
    −2: Exile target creature with power 4 or greater.

    — PLAY-ALL (Shorikai Vehicles). Rem Karolus's `prevent_damage` shield with ``recipient_union=["controller", {"exclude_self": True}]`` (you and
    other permanents you control), narrowed to noncombat sources (``source_filter: {"combat": False}``). The −2 is the parser's exile with a power gate.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "amount": "all", "recipient_union": ["controller", {"exclude_self": True}], "source_filter": {"combat": False},
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exile", {"target_kind": "creature", "creature_filter": {"min_power": 4}})],
            cost={"loyalty": -2},
        ),
    ]


register("The Wanderer", _the_wanderer)
