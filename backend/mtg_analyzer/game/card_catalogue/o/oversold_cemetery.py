from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _oversold_cemetery() -> list[AbilitySpec]:
    """At the beginning of your upkeep, if you have four or more creature cards in your graveyard, you may return target creature card from your graveyard to your hand.

    — PLAY-ALL Step 2 (Wretched Ranks). Wort, Boggart Auntie's upkeep return with a RULE 603.4 intervening-if
    (`trigger["active_if"]`, the shipped ``graveyard_card_type_count_at_least``).
    """
    return [AbilitySpec(
        "triggered",
        [EffectSpec("return_from_graveyard", {
            "target_kind": "graveyard_creature", "destination": "hand", "optional": True,
        })],
        trigger={
            "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you",
            "active_if": {"kind": "graveyard_card_type_count_at_least", "types": ["creature"], "amount": 4},
        },
    )]


register("Oversold Cemetery", _oversold_cemetery)
