from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _all_good_things() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after IV.)
    I, II, III — Draw two cards, then exile a card from your hand.
    IV — If all cards exiled with this Saga share a card type, you gain 10 life.
    """
    return [
        AbilitySpec("triggered", [
            EffectSpec("draw", {"count": 2}),
            EffectSpec("exile_hand_card", {"count": 1, "track_exiled_with": True}),
        ], trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1, 2, 3]}),
        AbilitySpec("triggered", [EffectSpec("gain_life", {"amount": 10},
            condition={"kind": "linked_exile_cards_share_type"})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [4]}),
    ]


register("All Good Things...", _all_good_things)
