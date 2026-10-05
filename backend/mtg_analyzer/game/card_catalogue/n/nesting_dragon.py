from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nesting_dragon() -> list[AbilitySpec]:
    'Flying\nLandfall — Whenever a land you control enters, create a 0/2 red Dragon Egg creature token with defender and "When this token dies, create a 2/2 red Dragon creature token with flying and \'{R}: This token gets +1/+0 until end of turn.\'"'
    # PLAY-ALL Step 2 (Temur Roar). The Egg's own dies trigger is not carried as token text: the
    # token is named "Dragon Egg", which `card_catalogue/d/dragon_egg.py` registers (the printed
    # card of that name has the identical ability), so it binds by name when the token is created.
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 0, "toughness": 2, "colors": ["R"],
                "subtypes": ["Dragon", "Egg"], "keywords": ["defender"], "token_name": "Dragon Egg",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
        ),
    ]


register("Nesting Dragon", _nesting_dragon)
