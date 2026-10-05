from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mr_foxglove() -> list[AbilitySpec]:
    """Whenever Mr. Foxglove attacks, draw cards equal to the number of cards in defending player's hand minus the
    number of cards in your hand. If you didn't draw cards this way, you may put a creature card from your hand
    onto the battlefield.

    — Peace Offering deck batch. "Didn't draw cards this way" is exactly "their hand isn't larger than yours" at
    the moment it resolves, so one `if_else` on `amount_compare` (their hand size vs yours) chooses between the
    draw (the new ``minus`` amount modifier takes an amount: their hand minus yours) and the optional creature
    drop (`put_from_hand_onto_battlefield`) — deciding up front also keeps the drawn cards from skewing the
    comparison. The defending player is the ATTACKS event's own ``attacked_player`` referent.
    """
    theirs = {"kind": "resource", "resource": "hand_size", "of": "attacked_player"}
    mine = {"kind": "resource", "resource": "hand_size", "of": "source"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "amount_compare", "left": theirs, "right": mine, "op": "gt"},
                "then": [{"type": "draw", "params": {"count": {**theirs, "minus": mine}}}],
                "else": [{"type": "put_from_hand_onto_battlefield", "params": {
                    "criteria": {"type": "creature"}, "count": 1, "optional": True,
                }}],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Mr. Foxglove", _mr_foxglove)
