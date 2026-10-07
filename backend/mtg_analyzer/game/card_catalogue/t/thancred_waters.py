from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thancred_waters() -> list[AbilitySpec]:
    """Flash
    Royal Guard — When Thancred Waters enters, another target legendary permanent you control gains indestructible for as long as you control Thancred Waters.
    Whenever you cast a noncreature spell, Thancred Waters gains indestructible until end of turn.

    — PLAY-ALL (Scions & Spellcraft). The ETB grants indestructible for
    as long as the trigger's controller controls Thancred on the battlefield.
    Losing control ends the effect permanently (RULE 611.2b). The noncreature
    cast trigger grants Thancred indestructible through the current turn.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "static": {"type": "grant_keyword", "params": {"keywords": ["indestructible"]}},
                "target_kind": "another_legendary_permanent_you_control",
                "condition": {"kind": "source_controlled_by_you"},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"keywords": ["indestructible"]})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"without_card_type": "creature"}},
        ),
    ]


register("Thancred Waters", _thancred_waters)
