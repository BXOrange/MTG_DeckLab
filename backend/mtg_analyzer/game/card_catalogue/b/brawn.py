from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _brawn() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Forest, creatures you control have trample.

    — Brawn, `_anger`'s green sibling (MEC-22): identical
    ``"from_graveyard": True`` shape, just trample/Forest in place of
    haste/Mountain. Brawn's own printed Trample (its first oracle-text
    line) needs no `AbilitySpec` of its own — that's the creature's plain
    printed keyword, read directly off `Card.keywords` by
    `combat.py`/`continuous.py` like any other, independent of this
    catalogue entry.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["trample"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_forest",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Brawn", _brawn)
