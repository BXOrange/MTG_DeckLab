from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _infantry_shield() -> list[AbilitySpec]:
    """Equipped creature has menace and mobilize X, where X is its power. (Whenever it attacks, create X tapped and attacking 1/1 red Warrior creature tokens. Sacrifice them at the beginning of the next end step.)
    Equip {2}

    — Infantry Shield. Equip comes from the keyword catalogue and menace is a layer-6 grant.
    The equipped creature owns the Mobilize attack trigger; its controller creates tapped,
    attacking Warriors equal to its power. The granted trigger survives removing the Shield
    after declaration, and exactly those tokens are sacrificed at the next end step.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["menace"]})],
        ),
        AbilitySpec("static", [EffectSpec("grant_triggered_ability", {
            "affects": "attached_permanent", "trigger_event": EventType.ATTACKS,
            "grant_effects": [
                {"type": "create_token", "params": {
                    "count": {"kind": "characteristic", "characteristic": "power", "of": "source"},
                    "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Warrior"],
                    "token_name": "Warrior", "tapped": True, "attacking": True,
                }},
                {"type": "create_delayed_trigger", "params": {
                    "step": "end", "scope": "any", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                }},
            ],
        })]),
    ]


register("Infantry Shield", _infantry_shield)
