from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _transpose() -> list[AbilitySpec]:
    """Draw a card, then discard a card. You lose 1 life. If this spell was cast from your hand, create a 0/1 black Wizard creature token with "Whenever you cast a noncreature spell, this token deals 1 damage to each opponent."
    Rebound (If you cast this spell from your hand, exile it as it resolves. At the beginning of your next upkeep, you may cast this card from exile without paying its mana cost.)

    — PLAY-ALL (Scions & Spellcraft). Rebound rides on its own empty-effects spec (``rebound=True``, as in Ephemerate). `draw`, `discard`, `lose_life`, then the Wizard token
    (as in Circle of Power) gated on the shipped ``was_cast_from_hand`` flag condition.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("discard", {"count": 1}),
                EffectSpec("lose_life", {"amount": 1}),
                EffectSpec("create_token", {
                    "count": 1, "power": 0, "toughness": 1, "colors": ["B"], "subtypes": ["Wizard"], "keywords": [],
                    "token_name": "Wizard",
                    "oracle_text": "Whenever you cast a noncreature spell, this token deals 1 damage to each opponent.",
                }, condition={"kind": "flag", "flag": "was_cast_from_hand"}),
            ],
        ),
        AbilitySpec("static", [], rebound=True),
    ]


register("Transpose", _transpose)
