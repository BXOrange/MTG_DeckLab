from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# Impulsive draw's dual-player extension — Ragavan, Nimble Pilferer's
# damaged-player-library exile + Mnemonic Betrayal's whole-graveyard, "any
# type" mana-wildcard exile. See `game/effects/library.py`'s `ImpulsiveDrawEffect`
# (``library_of="that_player"``)/`GraveyardImpulsiveCastEffect`/
# `ReturnRemainingExiledEffect`, `RulesEngine.exile_with_play_permission`/
# `exile_graveyard_with_cast_permission`, and `ManaPool`'s ``wildcard`` param.
# ---------------------------------------------------------------------------


def _ragavan_nimble_pilferer() -> list[AbilitySpec]:
    """Whenever Ragavan deals combat damage to a player, create a Treasure
    token and exile the top card of that player's library. Until end of
    turn, you may cast that card.
    Dash {1}{R}

    — Ragavan, Nimble Pilferer. One ordinary triggered ability over two
    effects, as printed: the Treasure, then `impulsive_draw` with
    ``library_of="that_player"`` (exile from the damaged player's library,
    permission stays with Ragavan's controller). Dash is a plain RULE 702
    keyword, covered by the keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {"token_name": "Treasure", "count": 1}),
                EffectSpec("impulsive_draw", {
                    "count": 1, "same_turn_only": True, "library_of": "that_player",
                }),
            ],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Ragavan, Nimble Pilferer", _ragavan_nimble_pilferer)
