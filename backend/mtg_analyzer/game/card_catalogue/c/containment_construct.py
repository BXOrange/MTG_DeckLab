from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# "whenever you discard a card, exile it from your graveyard,
# then you may play it this turn"
# ===========================================================================
# Engine: `ExileTriggeringDiscardMayPlayThisTurnEffect`
# ("exile_triggering_discard_may_play_this_turn").


def _containment_construct() -> list[AbilitySpec]:
    """Whenever you discard a card, you may exile that card from your
    graveyard. If you do, you may play that card this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_triggering_discard_may_play_this_turn", {})],
            trigger={"event": EventType.DISCARD_CARD, "condition": {"subject": "you"}},
        ),
    ]


register("Containment Construct", _containment_construct)
