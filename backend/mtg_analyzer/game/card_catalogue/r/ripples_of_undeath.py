from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ripples_of_undeath() -> list[AbilitySpec]:
    """At the beginning of your first main phase, mill three cards. Then you
    may pay {1} and 3 life. If you do, put a card from among those cards into
    your hand.
    """
    return [AbilitySpec("triggered", [
        EffectSpec("mill", {"count": 3, "capture_milled": True}),
        EffectSpec("pay_cost_then", {
            "cost": "{1}, Pay 3 life", "capture_previous": True,
            "effects": [{"type": "return_from_graveyard", "params": {
                "target_kind": "graveyard_card", "pick": True, "previous_pool": True,
                "destination": "hand",
            }}],
        }),
    ], trigger={"event": EventType.STEP_BEGIN, "step": "main1", "player": "you"})]


register("Ripples of Undeath", _ripples_of_undeath)
