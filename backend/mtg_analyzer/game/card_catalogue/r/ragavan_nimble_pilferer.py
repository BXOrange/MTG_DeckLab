from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# Impulsive draw's dual-player extension — Ragavan, Nimble Pilferer's
# damaged-player-library exile + Mnemonic Betrayal's whole-graveyard, "any
# type" mana-wildcard exile. See `game/effects/core.py`'s `ImpulsiveDrawEffect`/
# `GraveyardImpulsiveCastEffect`/`ReturnRemainingExiledEffect`,
# `RulesEngine._collect_impulsive_draw_triggers`/`exile_with_play_permission`/
# `exile_graveyard_with_cast_permission`, and `ManaPool`'s ``wildcard`` param.
# ---------------------------------------------------------------------------


def _ragavan_nimble_pilferer() -> list[AbilitySpec]:
    """Whenever Ragavan deals combat damage to a player, create a Treasure
    token and exile the top card of that player's library. Until end of
    turn, you may cast that card.
    Dash {1}{R}

    — Ragavan, Nimble Pilferer. Splits into two triggered abilities sharing
    the same "self deals combat damage to a player" condition: the Treasure
    token has no per-firing variance, so it's an ordinary bound
    `TriggeredAbility` below; the exile-and-cast-permission half needs the
    *damaged* player baked in fresh per firing (a bind-on-load ability's one
    fixed effects list can't carry that), so it's a marker
    (`impulsive_draw_on_combat_damage`) `RulesEngine.
    _collect_impulsive_draw_triggers` reads off the event's own source
    instead — see that method's docstring. Dash is a plain RULE 702 keyword,
    covered by the keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
        AbilitySpec(
            "static",
            [],
            impulsive_draw_on_combat_damage={"count": 1},
        ),
    ]


register("Ragavan, Nimble Pilferer", _ragavan_nimble_pilferer)
