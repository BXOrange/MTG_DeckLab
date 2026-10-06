from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kefka_dancing_mad() -> list[AbilitySpec]:
    """During your turn, Kefka has indestructible.
    At the beginning of your end step, exile a card at random from each opponent's graveyard. You may cast any number of spells from among cards exiled this way without paying their mana costs. Then each player who owns a spell you cast this way loses life equal to its mana value.

    — PLAY-ALL (Revival Trance). The indestructible line is the parser's (`grant_keyword`, ``active_if: your_turn``). The new `exile_random_graveyard_cards_cast_free`: one random card per opponent, a free-cast
    window for you on each nonland one (the Etali shape), and a marker that makes its owner lose life equal to its mana value
    when it is actually cast (`GameState.free_cast_owner_loses_life_ids`).
    **Simplification:** free casts use a turn-long window (including non-instant spells in the end step),
    with life loss after each cast rather than one during-resolution casting sequence.
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
