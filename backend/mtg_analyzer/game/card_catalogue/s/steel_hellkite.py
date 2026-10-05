from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _steel_hellkite() -> list[AbilitySpec]:
    """Flying
    {2}: This creature gets +1/+0 until end of turn.
    {X}: Destroy each nonland permanent with mana value X whose controller was dealt combat damage by
    this creature this turn. Activate only once each turn.

    — Keen Engineering deck batch. Flying is a keyword and the pump the parser's own claim. The
    {X} ability is a mass `destroy` over ``all_nonland_permanents`` filtered to mana value exactly X
    (``min_mana_value`` and ``max_mana_value`` both the ``"x"`` sentinel `_substitute_x` binds) and
    to controllers this creature dealt combat damage to this turn (the new
    ``controller_dealt_combat_damage_by_source`` filter), capped by the ``once_per_turn_marker``.
    """
    return [
        AbilitySpec("activated", [EffectSpec("pump", {"power": 1, "toughness": 0})], cost={"text": "{2}"}),
        AbilitySpec(
            "activated",
            [
                EffectSpec("destroy", {
                    "selector": "all_nonland_permanents",
                    "filter": {"min_mana_value": "x", "max_mana_value": "x",
                               "controller_dealt_combat_damage_by_source": True},
                }),
                EffectSpec("once_per_turn_marker", {}),
            ],
            cost={"text": "{X}"},
        ),
    ]


register("Steel Hellkite", _steel_hellkite)
