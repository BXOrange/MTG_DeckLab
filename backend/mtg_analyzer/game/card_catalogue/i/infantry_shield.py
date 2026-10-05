from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _infantry_shield() -> list[AbilitySpec]:
    """Equipped creature has menace and mobilize X, where X is its power. (Whenever it attacks, create X tapped and attacking 1/1 red Warrior creature tokens. Sacrifice them at the beginning of the next end step.)
    Equip {2}

    — Infantry Shield. Equip comes from the keyword catalogue and menace is a layer-6 grant. Mobilize (RULE
    702.181) has no engine behaviour of its own yet (the keyword row is recognition only), so it is authored
    as the Equipment's own trigger on "equipped creature attacks" — the same observable result as the
    creature's granted ability: X = the attacker's power (`characteristic` of the trigger subject), X tapped and
    attacking Warriors, and Stangg's delayed sacrifice of exactly the tokens created (``capture``) at the
    beginning of the next end step.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["menace"]})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": {"kind": "characteristic", "characteristic": "power", "of": "trigger_subject"},
                    "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Warrior"],
                    "token_name": "Warrior", "tapped": True, "attacking": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Mobilize: erzeugte Krieger opfern",
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Infantry Shield", _infantry_shield)
