from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thancred_waters() -> list[AbilitySpec]:
    """Flash
    Royal Guard — When Thancred Waters enters, another target legendary permanent you control gains indestructible for as long as you control Thancred Waters.
    Whenever you cast a noncreature spell, Thancred Waters gains indestructible until end of turn.

    — PLAY-ALL (Scions & Spellcraft). Flash is the keyword's. The ETB is a `grant_until` (Shield Broker/Pyreswipe Hawk) of the
    indestructible keyword on the new ``another_legendary_permanent_you_control`` target, bounded by ``source_on_battlefield``
    (**simplification:** "as long as you control" is read as "while it remains on the battlefield"). The cast trigger is the parser's.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "static": {"type": "grant_keyword", "params": {"keywords": ["indestructible"]}},
                "target_kind": "another_legendary_permanent_you_control",
                "condition": {"kind": "source_on_battlefield"},
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
