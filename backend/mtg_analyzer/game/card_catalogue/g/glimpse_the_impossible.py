from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _glimpse_the_impossible() -> list[AbilitySpec]:
    """Exile the top three cards of your library. You may play those cards this turn. At the beginning of the next end step, if any of those cards remain exiled, put them into your graveyard, then create a 0/1 colorless Eldrazi Spawn creature token for each card put into your graveyard this way. Those tokens have "Sacrifice this token: Add {C}."

    — Commander Cube singleton batch. The exile and the this-turn play window are `ImpulsiveDrawEffect` (RULE 601.3b);
    the end-step leftover cleanup is a RULE 603.7 delayed trigger armed by `glimpse_arm_cleanup`
    (`game/effects/exile_top_pool.py`), which moves only the cards still in exile and makes one spawn per card moved.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("seq", {"effects": [
            {"type": "impulsive_draw", "params": {"count": 3, "same_turn_only": True}},
            {"type": "glimpse_arm_cleanup", "params": {}},
        ]})]),
    ]


register("Glimpse the Impossible", _glimpse_the_impossible)
