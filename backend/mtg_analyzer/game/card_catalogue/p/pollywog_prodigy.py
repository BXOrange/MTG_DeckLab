from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pollywog_prodigy() -> list[AbilitySpec]:
    """Evolve (Whenever a creature you control enters, if that creature has greater power or toughness than
    this creature, put a +1/+1 counter on this creature.)
    Whenever an opponent casts a noncreature spell with mana value less than this creature's power, draw a
    card.

    — Family Matters deck batch. Evolve is the engine's RULE 702.100 keyword. The second ability is a
    `SPELL_CAST` by an opponent, noncreature (``spell_exclude_card_types``), gated by the new
    ``spell_mana_value_less_than_source_power`` (the spell's mana value against this creature's current
    power).
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
                "spell_mana_value_less_than_source_power": True,
            },
        ),
    ]


register("Pollywog Prodigy", _pollywog_prodigy)
