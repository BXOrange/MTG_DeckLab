from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _theater_of_horrors() -> list[AbilitySpec]:
    """At the beginning of your upkeep, exile the top card of your library.
    During your turn, if an opponent lost life this turn, you may play lands and cast spells from among cards exiled with this enchantment.
    {3}{R}: This enchantment deals 1 damage to target opponent or planeswalker.

    — PLAY-ALL (Endless Punishment). The ping is the parser's. The upkeep exile is Neriv's `exile_top_of_library` (``track_exiled_with``) followed by its
    standing `grant_conditional_cast_from_exile` over every card exiled with this enchantment, here gated on it being your turn *and* an opponent having lost
    life this turn (the shared state-condition vocabulary).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_top_of_library", {"count": 1, "track_exiled_with": True}),
                EffectSpec("grant_conditional_cast_from_exile", {
                    "all_cards": True, "linked_source": True,
                    "condition": {"kind": "all", "conditions": [
                        {"kind": "your_turn"}, {"kind": "opponent_lost_life_this_turn", "min": 1},
                    ]},
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 1, "target_kind": "opponent_or_planeswalker"})],
            cost={"text": "{3}{r}"},
        ),
    ]


register("Theater of Horrors", _theater_of_horrors)
