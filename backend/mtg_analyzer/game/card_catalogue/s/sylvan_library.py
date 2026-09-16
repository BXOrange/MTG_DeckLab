from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sylvan_library() -> list[AbilitySpec]:
    """Sylvan Library (Enchantment, {1}{G})

    "At the beginning of your draw step, you may draw two additional
    cards. If you do, choose two cards in your hand drawn this turn. For
    each of those cards, pay 4 life or put the card on top of your
    library."

    The whole "you may draw… if you do, choose… for each, pay-or-return"
    sequence is `SylvanLibraryEffect` (MEC-40) — see its own docstring for
    the documented "always the two just-drawn cards" simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sylvan_library", {"life": 4, "count": 2})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "draw"}, "phase_relation": "you",
            },
            optional=True,
        ),
    ]


register("Sylvan Library", _sylvan_library)
