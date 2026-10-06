from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _occult_epiphany() -> list[AbilitySpec]:
    """Draw X cards, then discard X cards. Create a 1/1 white Spirit creature token with flying for each card type among cards
    discarded this way.

    — PLAY-ALL (Multiverse Reforged). `mark_event_log` opens the "this way" window (Mog, Moogle Warrior's idiom), then the plain
    `draw`/`discard` over the spell's X, then `tokens_per_discarded_card_type`: one Spirit per distinct card type among the
    ``DISCARD_CARD`` events logged since the mark (a multi-type card such as an artifact creature counts both types).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("mark_event_log", {}),
                EffectSpec("draw", {"count": "x"}),
                EffectSpec("discard", {"count": "x"}),
                EffectSpec("tokens_per_discarded_card_type", {"token": {
                    "token_name": "Spirit", "power": 1, "toughness": 1, "colors": ["W"],
                    "subtypes": ["Spirit"], "keywords": ["flying"],
                }}),
            ],
        ),
    ]


register("Occult Epiphany", _occult_epiphany)
