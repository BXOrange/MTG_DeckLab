from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scriv_the_obligator() -> list[AbilitySpec]:
    """Flying, deathtouch (fold in).
    Whenever Scriv enters or attacks, create a white Aura enchantment token
    named Contract attached to target creature an opponent controls."""
    make = EffectSpec("seq", {"effects": [
        {"type": "create_token", "params": {
            "token_name": "Contract", "colors": ["W"], "subtypes": ["Aura"],
            "oracle_text": "Enchant creature",
        }},
        {"type": "attach", "params": {
            "mover": "created", "target_kind": "creature_you_dont_control",
        }},
    ]})
    return [
        AbilitySpec(
            "triggered", [make],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered", [make],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Scriv, the Obligator", _scriv_the_obligator)
