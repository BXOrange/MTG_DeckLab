from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _formidable_speaker() -> list[AbilitySpec]:
    """When this creature enters, you may discard a card. If you do,
    search your library for a creature card, reveal it, put it into your
    hand, then shuffle.
    {1}, {T}: Untap another target permanent.

    — Eliferate deck batch. The ETB is `pay_cost_then` (RULE 118.3) —
    "discard a card" as the optional payment, the search as its "if you
    do" tail; the reveal step isn't separately modeled, the same
    simplification every tutor in this catalogue already makes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "Discard a card",
                "effects": [{"type": "search", "params": {"criteria": "Creature", "destination": "hand"}}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"untap": True, "target_kind": "permanent"})],
            cost={"text": "{1}, {T}"},
        ),
    ]


register("Formidable Speaker", _formidable_speaker)
