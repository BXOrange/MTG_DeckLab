from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _birgi_god_of_storytelling() -> list[AbilitySpec]:
    """Whenever you cast a spell, add {R}. Until end of turn, you don't
    lose this mana as steps and phases end.
    Creatures you control can boast twice during each of your turns
    rather than once.

    — Imodane deck batch. **Documented simplification**: modeled as a
    plain "whenever you cast a spell, add {R}" (the mana empties at the
    end of the current step/phase as usual, RULE 500.4 — no primitive
    marks specific floating mana as persisting past that) — no mana
    *ritual* value is lost for a spell cast with priority still to
    follow, only the "bank it for later this turn" upside. "Boast twice"
    isn't modeled at all: RULE 702.161's Boast keyword itself has no
    engine primitive yet (no Boast-printing card is in either deck), so
    there's nothing to double.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["R"]})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
            },
        ),
    ]


register("Birgi, God of Storytelling", _birgi_god_of_storytelling)
register("Birgi, God of Storytelling // Harnfel, Horn of Bounty", _birgi_god_of_storytelling)
