from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dragon_egg() -> list[AbilitySpec]:
    """Defender
    When this creature dies, create a 2/2 red Dragon creature token with flying and "{R}: This creature gets +1/+0 until end of turn."

    — PLAY-ALL Step 2 (Temur Roar). Registered under the printed card's name
    *and* the 0/2 token Nesting Dragon creates, which share the name and the
    ability ("When this token dies" is the same trigger). The parser can't
    claim a created token whose granted ability is itself a quoted ability,
    so the Dragon token carries its pump as inline token text (parsed on its
    own as a plain `{R}: +1/+0` activated ability). Defender is a keyword.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["R"], "subtypes": ["Dragon"],
                "keywords": ["flying"], "token_name": "Dragon",
                "oracle_text": "Flying\n{R}: This creature gets +1/+0 until end of turn.",
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Dragon Egg", _dragon_egg)
