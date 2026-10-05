from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tenuous_truce() -> list[AbilitySpec]:
    """Enchant opponent
    At the beginning of enchanted opponent's end step, you and that player each draw a card.
    When you attack enchanted opponent or a planeswalker they control or when they attack you or a planeswalker
    you control, sacrifice this Aura.

    — Peace Offering deck batch. "Enchant opponent" is the Aura's cast-time keyword (a player target restricted
    to opponents). The end-step trigger is the new ``phase_relation="enchanted_player"`` (the active player is
    the one the Aura is attached to) with `draw`'s player operand reading the new ``enchanted_player`` referent.
    The sacrifice is an `ATTACKERS_DECLARED` trigger scoped by ``attack_between_controller_and_enchanted`` — an
    attack in either direction between this Aura's controller and the enchanted player, planeswalkers included
    (`GameEngine._fire_player_attacked_events` now reports ``defended_player_ids``) — whose body is
    `sacrifice_self`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("draw", {"count": 1, "player": {"of": "enchanted_player"}}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "enchanted_player"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={"event": EventType.ATTACKERS_DECLARED, "attack_between_controller_and_enchanted": True},
        ),
    ]


register("Tenuous Truce", _tenuous_truce)
