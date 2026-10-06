from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grab_the_prize() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, discard a card.
    Draw two cards. If the discarded card wasn't a land card, Grab the Prize deals 2 damage to each opponent.

    — PLAY-ALL (Endless Punishment). The additional cost and the draw are the parser's. The engine now remembers the card types of what the discard cost threw away
    (`GameObject.discarded_cost_card_types`), read by the new ``discarded_cost_card_is`` condition inside an `if_else` around the damage (negated: "wasn't a land card").
    """
    return [
        AbilitySpec("spell_effect", [], additional_cost={"discard": 1}),
        AbilitySpec("spell_effect", [
            EffectSpec("draw", {"count": 2}),
            EffectSpec("if_else", {
                "condition": {"kind": "not", "condition": {"kind": "discarded_cost_card_is", "card_type": "land"}},
                "then": [{"type": "damage", "params": {"amount": 2, "selector": "each_opponent"}}],
            }),
        ]),
    ]


register("Grab the Prize", _grab_the_prize)
