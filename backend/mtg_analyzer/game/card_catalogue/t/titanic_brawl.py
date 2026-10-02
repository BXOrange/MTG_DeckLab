from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _titanic_brawl() -> list[AbilitySpec]:
    """This spell costs {1} less to cast if it targets a creature you control
    with a +1/+1 counter on it.
    Target creature you control fights target creature you don't control.
    (Each deals damage equal to its power to the other.)

    — PLAY-ALL Step 2 (Kodama). The fight is the parser's own claim,
    reproduced verbatim. The discount is the Ajani's Response shape: a
    ``affects="self"`` `cost_reduction` with ``reduce_if_targets`` (RULE
    601.2f, checked once the targets are chosen) whose criteria carry
    ``controller: you`` and ``has_counter_kind`` — so only *my* creature with
    a +1/+1 counter qualifies; the opponent's target never does, even if it
    has a counter.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1,
                "reduce_if_targets": {"card_type": "creature", "controller": "you", "has_counter_kind": "+1/+1"},
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("fight", {
                "fighter_kind": "creature_you_control", "other_kind": "creature_you_dont_control",
            })],
        ),
    ]


register("Titanic Brawl", _titanic_brawl)
