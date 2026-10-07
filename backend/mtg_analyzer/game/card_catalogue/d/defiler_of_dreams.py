from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from .defiler_of_vigor import _PERMANENT_TYPES


def _defiler_of_dreams() -> list[AbilitySpec]:
    """Flying
    As an additional cost to cast blue permanent spells, you may pay 2 life.
    Those spells cost {U} less to cast if you paid life this way. This effect
    reduces only the amount of blue mana you pay.
    Whenever you cast a blue permanent spell, draw a card.

    — PLAY-ALL Step 2 (yshtola). The blue twin of Defiler of Vigor: the same
    `pip_life_option` static with an announced optional life payment and the
    same `any_of` permanent-types filter on the trigger (the parser's own
    claim drops the word "permanent" and would fire for a blue instant too).
    Casting offers the payment explicitly, including when blue mana is available.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pip_life_option", {
                "color": "U", "pips": 1, "spell_color": "U", "spell_type": list(_PERMANENT_TYPES),
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "you"},
                "spell_filter": {"color": "U", "any_of": [{"card_type": t} for t in _PERMANENT_TYPES]},
            },
        ),
    ]


register("Defiler of Dreams", _defiler_of_dreams)
