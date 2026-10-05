from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dragonhawk_fate_s_tempest() -> list[AbilitySpec]:
    """Flying
    Whenever Dragonhawk enters or attacks, exile the top X cards of your library, where X is the number of
    creatures you control with power 4 or greater. You may play those cards until your next end step. At the
    beginning of your next end step, Dragonhawk deals 2 damage to each opponent for each of those cards that
    are still exiled.

    — Reign of Dragons deck batch. Flying is a keyword. One self trigger on either event whose body is
    `exile_top_play_then_burn` (`ExileTopPlayThenBurnEffect`): X counted by a structured
    creature-power selector, the cards playable this turn, and a delayed end-step trigger dealing the
    damage per card still exiled.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_play_then_burn", {
                "count_selector": {"zone": "battlefield", "of": "you",
                                   "filter": {"card_type": "creature", "min_power": 4}},
                "amount": 2,
            })],
            trigger={"event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS], "condition": {"subject": "self"}},
        ),
    ]


register("Dragonhawk, Fate's Tempest", _dragonhawk_fate_s_tempest)
