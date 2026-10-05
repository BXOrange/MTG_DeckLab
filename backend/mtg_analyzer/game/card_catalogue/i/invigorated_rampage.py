from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invigorated_rampage() -> list[AbilitySpec]:
    """Choose one —
    • Target creature gets +4/+0 and gains trample until end of turn.
    • Two target creatures each get +2/+0 and gain trample until end of turn.

    — PLAY-ALL Step 2 (Wick Snail Boom). A modal spell (RULE 700.2, Archdruid's
    Charm's ``modes`` shape): each option is one `pump` with a trample grant —
    the second over ``target_count: 2`` (both targets chosen on announcement).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "options": [
                    [EffectSpec("pump", {
                        "power": 4, "toughness": 0, "keywords": ["trample"], "target_kind": "creature",
                    })],
                    [EffectSpec("pump", {
                        "power": 2, "toughness": 0, "keywords": ["trample"], "target_kind": "creature",
                        "target_count": 2,
                    })],
                ],
                "descriptions": [
                    "Eine Zielkreatur erhält +4/+0 und Trample bis zum Ende des Zuges.",
                    "Zwei Zielkreaturen erhalten je +2/+0 und Trample bis zum Ende des Zuges.",
                ],
            },
        ),
    ]


register("Invigorated Rampage", _invigorated_rampage)
