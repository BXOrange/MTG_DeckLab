from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Cards milled by the enter trigger.
_MILL_COUNT = 3


def _blanchwood_prowler() -> list[AbilitySpec]:
    """When this creature enters, mill three cards. You may put a land card from among the cards milled this way into your hand. If you don't, put a +1/+1 counter on this creature. (To mill a card, put the top card of your library into your graveyard.)

    One `mill_recover_card_else` effect (`effects/mill_recover_card.py`): it mills, then offers a land card from
    that exact mill batch for the hand (Cache Grab's recover step), and the counter rides the "if you don't"
    branch -- taken when no land was milled or the offer is declined (RULE 701.17).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mill_recover_card_else", {
                "count": _MILL_COUNT, "card_type": "land",
                "else_effects": [{"type": "add_counters", "params": {
                    "kind": "+1/+1", "amount": 1, "target_kind": None}}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Blanchwood Prowler", _blanchwood_prowler)
