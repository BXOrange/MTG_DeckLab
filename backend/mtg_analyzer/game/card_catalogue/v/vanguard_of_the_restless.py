from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# "for each time you've cast your commander from the command zone"
# ===========================================================================
# Engine: `continuous.count_selector` ``commander_casts_this_game`` (sum of
# `Player.commander_casts`).


def _vanguard_of_the_restless() -> list[AbilitySpec]:
    """Flying
    Spirits you control get +1/+1 for each time you've cast your commander
    from the command zone this game.
    Whenever a Spirit you control enters, you may pay {2}{W}. If you do,
    return this card from your graveyard to the battlefield."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "subtype": "Spirit",
                "power": 1, "toughness": 1,
                "power_count": "commander_casts_this_game",
                "toughness_count": "commander_casts_this_game",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "pay {2}{W}",
                "effects": [{"type": "return_self_from_graveyard", "params": {"tapped": False}}],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "subtypes": ["spirit"], "nontoken": False,
                              "controller": "you", "other": False},
            },
        ),
    ]


register("Vanguard of the Restless", _vanguard_of_the_restless)
