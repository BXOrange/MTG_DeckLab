from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chocobo_knights() -> list[AbilitySpec]:
    """Whenever you attack, creatures you control with counters on them gain double strike until end of turn.

    — PLAY-ALL (Counter Blitz). `ATTACKERS_DECLARED` (Adeline's "whenever you attack") over `pump` of the structured group of creatures
    you control that have a counter (``has_counter``); the group is read as the keyword is granted.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"keywords": ["double strike"], "selector": {
                "zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "has_counter": True},
            }})],
            trigger={"event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"}},
        ),
    ]


register("Chocobo Knights", _chocobo_knights)
