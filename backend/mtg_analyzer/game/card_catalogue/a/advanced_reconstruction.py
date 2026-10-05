from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Advanced Reconstruction (hand-authored Class) — PAR-60
# ===========================================================================
# Level 1: new `advanced_reconstruction_l1` effect (mill + random graveyard
# trigger (Quintorius / Spirit of Resilience family) -> 2 damage to each
# opponent. Level 3: `cost_reduction` with the new ``not_from_hand`` param.


def _advanced_reconstruction() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    At the beginning of your first main phase, mill a card, then exile a
    card from your graveyard at random. You may play the exiled card this
    turn.
    {1}{R}: Level 2
    Whenever one or more cards leave your graveyard, this Class deals 2
    damage to each opponent.
    {1}{R}: Level 3
    Spells you cast from anywhere other than your hand cost {2} less to
    cast."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("advanced_reconstruction_l1", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main1"},
                     "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 2})],
            cost={"text": "{1}{R}", "sorcery_speed_only": True, "class_level": 2},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "each_opponent"})],
            trigger={
                "event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you",
                "min_level": 2, "level_counter": "class_level",
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 3})],
            cost={"text": "{1}{R}", "sorcery_speed_only": True, "class_level": 3},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 2, "not_from_hand": True,
                "min_level": 3, "level_counter": "class_level",
            })],
        ),
    ]


register("Advanced Reconstruction", _advanced_reconstruction)
