from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_master_of_keys() -> list[AbilitySpec]:
    """Flying
    When The Master of Keys enters, put X +1/+1 counters on it and mill twice X cards.
    Each enchantment card in your graveyard has escape. The escape cost is equal to the card's mana cost plus exile three other cards from your graveyard. (You may cast cards from your graveyard for their escape cost.)

    — PLAY-ALL (Miracle Worker). Flying is the keyword's. The ETB is the parser's `add_counters` + `mill` (``twice_x``), X being the X the
    permanent was cast with (RULE 107.3m). The escape grant is Underworld Breach's `grant_escape` narrowed to ``enchantment`` cards.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": "x", "kind": "+1/+1"}), EffectSpec("mill", {"count": "twice_x"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_escape", {"card_type": "enchantment", "nonland_only": True, "exile_from_graveyard": 3})],
        ),
    ]


register("The Master of Keys", _the_master_of_keys)
