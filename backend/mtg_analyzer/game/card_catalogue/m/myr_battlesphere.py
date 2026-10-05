from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _myr_battlesphere() -> list[AbilitySpec]:
    """When this creature enters, create four 1/1 colorless Myr artifact creature tokens.
    Whenever this creature attacks, you may tap X untapped Myr you control. If you do, this creature
    gets +X/+0 until end of turn and deals X damage to the player or planeswalker it's attacking.

    — Keen Engineering deck batch. The ETB is the parser's own claim. The attack trigger is the
    chooser (`choose_objects`, a ``subtype:myr`` pick of any number of untapped ones, optional) whose
    ``then_that_many`` body gets X = how many were tapped: a self `pump` and `damage` with the new
    ``attacked_object`` selector (the player *or planeswalker* this attacker was declared against).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 4, "power": 1, "toughness": 1, "colors": [], "subtypes": ["Myr"], "keywords": [],
                "is_artifact": True, "token_name": "Myr",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {
                "action": "tap", "what": "subtype:myr", "count": "all", "optional": True,
                "require_untapped": True,
                "then_that_many": {"effects": [
                    {"type": "pump", "params": {"power": "x", "toughness": 0, "target_kind": None}},
                    {"type": "damage", "params": {"amount": "x", "selector": "attacked_object"}},
                ]},
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Myr Battlesphere", _myr_battlesphere)
