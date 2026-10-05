from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _naktamun_lorespinner() -> list[AbilitySpec]:
    """At the beginning of your upkeep, if a player has one or fewer cards in
    hand, this creature becomes prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "any_player_cards_in_hand_at_most", "amount": 1},
            },
        ),
    ]


register("Naktamun Lorespinner", _naktamun_lorespinner)
register("Naktamun Lorespinner // Wheel of Fortune", _naktamun_lorespinner)
