from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kefka_dancing_mad() -> list[AbilitySpec]:
    """During your turn, Kefka has indestructible.
    At the beginning of your end step, exile a card at random from each opponent's graveyard. You may cast any number of spells from among cards exiled this way without paying their mana costs. Then each player who owns a spell you cast this way loses life equal to its mana value.

    The standing indestructible condition is the parser’s. The end-step
    ability exiles once per opponent, offers repeated casts during resolution
    (RULE 608.2g), then applies owner life loss from the spells actually cast.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "self", "keywords": ["indestructible"], "active_if": {"kind": "your_turn"}})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_random_graveyard_cards_cast_free", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Kefka, Dancing Mad", _kefka_dancing_mad)
