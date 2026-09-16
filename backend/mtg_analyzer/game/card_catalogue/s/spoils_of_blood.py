from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spoils_of_blood() -> list[AbilitySpec]:
    """Spoils of Blood (Instant, {B})

    "Create an X/X black Horror creature token, where X is the number of
    creatures that died this turn."

    `CreateTokenEffect`'s new ``pt_from_count_selector`` param plus
    `continuous.count_selector`'s new ``"creatures_died_this_turn"`` entry
    (both MEC-43 round 4C) — the board-count sibling of the already-
    shipped ``pt_from_trigger_event`` (an X/X token sized off a firing
    event's own field instead of a live board count).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("create_token", {
                "count": 1, "colors": ["B"], "subtypes": ["Horror"],
                "pt_from_count_selector": "creatures_died_this_turn",
            })],
        )
    ]


register("Spoils of Blood", _spoils_of_blood)
