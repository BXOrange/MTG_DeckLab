from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ajanis_chosen() -> list[AbilitySpec]:
    """Whenever an enchantment you control enters, create a 2/2 white Cat
    creature token. If that enchantment is an Aura, you may attach it to the
    token.

    Documented simplification: only the token creation is modeled; the "if
    it's an Aura, attach it to the token" rider is dropped (a re-attach of
    the just-entered Aura — a corner these decks don't lean on)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Cat", "power": 2, "toughness": 2,
                "colors": ["W"], "subtypes": ["Cat"],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "enchantment", "controller": "you"},
            },
        ),
    ]


register("Ajani's Chosen", _ajanis_chosen)
