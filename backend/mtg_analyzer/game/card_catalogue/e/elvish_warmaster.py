from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elvish_warmaster() -> list[AbilitySpec]:
    """Whenever one or more other Elves you control enter, create a 1/1
    green Elf Warrior creature token. This ability triggers only once each
    turn.
    {5}{G}{G}: Elves you control get +2/+2 and gain deathtouch until end of
    turn.

    — Eliferate deck batch. The pump ability already parses; the ETB
    trigger is the same "whenever one or more other X you control enter…
    triggers only once each turn" shape `Merry, Warden of Isengard` already
    uses for artifacts, just subtype-scoped to Elf instead of type-scoped
    to artifact.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Warrior"], "keywords": [], "token_name": "Elf Warrior",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "subtypes": ["elf"],
                    "controller": "you", "other": True,
                },
                "limit": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 2, "toughness": 2, "keywords": ["deathtouch"],
                "selector": "creatures_you_control_of_type_elf",
            })],
            cost={"text": "{5}{G}{G}"},
        ),
    ]


register("Elvish Warmaster", _elvish_warmaster)
