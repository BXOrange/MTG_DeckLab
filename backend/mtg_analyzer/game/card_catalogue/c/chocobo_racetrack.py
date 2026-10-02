from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chocobo_racetrack() -> list[AbilitySpec]:
    """Landfall — Whenever a land you control enters, create a 2/2 green
    Bird creature token with "Whenever a land you control enters, this token
    gets +1/+0 until end of turn."

    — PLAY-ALL Step 2 (Kodama). The landfall trigger is the parser's
    "whenever a land you control enters" group head with a `create_token`;
    the quoted trigger rides on the token's own ``oracle_text`` (a token's
    abilities are bound from its text, like Freyalise's mana Elf), whose
    "this token gets +1/+0 until end of turn" the parser claims on its own
    (probed with "this creature"; the token form is pinned by the test).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["G"],
                "subtypes": ["Bird"], "keywords": [], "token_name": "Bird",
                "oracle_text": "Whenever a land you control enters, this token gets +1/+0 until end of turn.",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
        ),
    ]


register("Chocobo Racetrack", _chocobo_racetrack)
