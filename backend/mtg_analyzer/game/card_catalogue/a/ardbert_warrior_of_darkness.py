from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _legends() -> dict:
    """"each legendary creature you control" as a structured selector (`add_counters`' ``group`` only reads this shape)."""
    return {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "legendary": True}}


def _ardbert_warrior_of_darkness() -> list[AbilitySpec]:
    """Whenever you cast a white spell, put a +1/+1 counter on each legendary creature you control. They gain vigilance until end of turn.
    Whenever you cast a black spell, put a +1/+1 counter on each legendary creature you control. They gain menace until end of turn.

    — PLAY-ALL (Scions & Spellcraft). Two colour-filtered cast triggers. `add_counters` over the structured legendary-creatures-you-control
    group, then `pump` over the same group for the keyword ("they" is that group — counters cannot take a creature out of it).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "group": _legends()}),
                EffectSpec("pump", {"keywords": ["vigilance"], "selector": _legends()}),
            ],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"color": "W"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "group": _legends()}),
                EffectSpec("pump", {"keywords": ["menace"], "selector": _legends()}),
            ],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"color": "B"}},
        ),
    ]


register("Ardbert, Warrior of Darkness", _ardbert_warrior_of_darkness)
