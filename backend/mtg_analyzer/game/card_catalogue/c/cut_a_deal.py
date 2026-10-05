from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cut_a_deal() -> list[AbilitySpec]:
    """Each opponent draws a card, then you draw a card for each opponent who drew a card this way.

    — Family Matters deck batch. Each opponent's draw, then your own draw counted by the
    ``opponents_you_have`` selector. **Documented simplification:** an opponent with an empty library (who
    would lose the game on that draw rather than draw) still counts — the player is out of the game by the
    state-based action anyway.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("draw", {"count": 1, "selector": "each_opponent"}),
            EffectSpec("draw", {"count_selector": "opponents_you_have"}),
        ]),
    ]


register("Cut a Deal", _cut_a_deal)
