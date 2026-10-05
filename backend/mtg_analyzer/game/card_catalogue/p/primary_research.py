from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _primary_research() -> list[AbilitySpec]:
    """When this enchantment enters, return target nonland permanent card
    with mana value 3 or less from your graveyard to the battlefield.
    At the beginning of your end step, if a card left your graveyard this
    turn, draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_nonland_permanent", "destination": "battlefield",
                "max_mana_value": 3,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
                "active_if": {"kind": "card_left_graveyard_this_turn"},
            },
        ),
    ]


register("Primary Research", _primary_research)
