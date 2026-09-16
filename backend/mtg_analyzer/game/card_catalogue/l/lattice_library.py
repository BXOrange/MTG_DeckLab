from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lattice_library() -> list[AbilitySpec]:
    """This enchantment enters with X study counters on it.
    When this enchantment enters and whenever you cast your first spell with
    {X} in its mana cost each turn, create a 0/0 green and blue Fractal
    creature token. Put a number of +1/+1 counters on it equal to the number
    of study counters on this enchantment."""
    def _make():
        return EffectSpec("create_token", {
            "count": 1, "token_name": "Fractal", "power": 0, "toughness": 0,
            "colors": ["G", "U"], "subtypes": ["Fractal"],
            "extra_counters": {"kind": "+1/+1",
                               "count_from_count_selector": "study_counters_on_source"},
        })
    return [
        AbilitySpec(
            "triggered", [_make()],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered", [_make()],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "first_x_spell": True,
            },
        ),
    ]


register("Lattice Library", _lattice_library)
