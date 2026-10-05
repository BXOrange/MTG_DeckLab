from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _prophet_of_the_scarab() -> list[AbilitySpec]:
    """Vigilance
    When this creature enters, draw cards equal to the number of Zombies you control or the number of Zombie cards in your graveyard, whichever is greater.
    Embalm {5}{U}

    — PLAY-ALL Step 2 (Eternal Might). Vigilance/Embalm are printed keywords. The enter trigger is a `bind` over
    the new `greater_of` amount: the larger of two structured counts (Zombies on your battlefield, Zombie cards in
    your graveyard). It counts itself on the battlefield, as printed.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {
                    "kind": "greater_of",
                    "left": {"kind": "count_selector", "selector": {
                        "zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "subtype": "zombie"}}},
                    "right": {"kind": "count_selector", "selector": {
                        "zone": "graveyard", "of": "you", "filter": {"subtype": "zombie"}}},
                },
                "effects": [{"type": "draw", "params": {"count": "$n"}}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Prophet of the Scarab", _prophet_of_the_scarab)
