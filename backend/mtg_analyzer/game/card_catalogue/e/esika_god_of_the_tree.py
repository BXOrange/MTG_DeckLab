from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

_ANY_COLOR = [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]


def _esika_god_of_the_tree() -> list[AbilitySpec]:
    """Vigilance
    {T}: Add one mana of any color.
    Other legendary creatures you control have vigilance and "{T}: Add one
    mana of any color."

    — PLAY-ALL (SpongeBob). Esika grants vigilance and a five-color mana
    ability to other legendary creatures. The modal back face has a separate
    catalogue entry: The Prismatic Bridge reveals until a creature or
    planeswalker, resolving entry replacements before it enters and randomly
    bottoming the other revealed cards without an exile zone change.
    """
    legendary = {"legendary": True}
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "object_filter": dict(legendary),
                "keywords": ["vigilance"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "mana": [dict(option) for option in _ANY_COLOR],
                "affects": "other_creatures_you_control", "object_filter": dict(legendary),
            })],
        ),
    ]


register("Esika, God of the Tree", _esika_god_of_the_tree)


def _prismatic_bridge() -> list[AbilitySpec]:
    """Reveal until a creature or planeswalker enters at your upkeep."""
    return [AbilitySpec(
        "triggered",
        [EffectSpec("reveal_until", {
            "criteria": {"type": ["creature", "planeswalker"]}, "entry_choices": True,
        })],
        trigger={"event": "STEP_BEGIN", "filter": {"step": "upkeep"}, "phase_relation": "you"},
    )]


register("The Prismatic Bridge", _prismatic_bridge)
