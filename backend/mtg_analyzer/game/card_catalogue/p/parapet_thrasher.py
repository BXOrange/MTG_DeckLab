from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _parapet_thrasher() -> list[AbilitySpec]:
    """Flying
    Whenever one or more Dragons you control deal combat damage to an opponent, choose one that hasn't been
    chosen this turn —
    • Destroy target artifact that opponent controls.
    • This creature deals 4 damage to each other opponent.
    • Exile the top card of your library. You may play it this turn.

    — Reign of Dragons deck batch. Flying is a keyword. The head is the parser's batched
    `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` group trigger (Dragons you control, recipient an opponent) and
    the block uses the modal grammar's ``exhaust_per_turn`` ("hasn't been chosen this turn"). The bullets:
    `destroy` over ``artifact_that_player_controls`` ("that opponent" = the damaged player, read off the
    firing event), `damage` with the ``each_other_opponent`` selector, and the impulsive draw.
    """
    return [
        AbilitySpec(
            "triggered", [],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "group", "controller": "you", "other": False,
                              "filter": {"subtype": "dragon"}, "recipient_is_opponent": True},
                "contributors": {"min": 1},
            },
            modes={
                "choose": 1, "exhaust_per_turn": True,
                "options": [
                    [EffectSpec("destroy", {"target_kind": "artifact_that_player_controls"})],
                    [EffectSpec("damage", {"amount": 4, "selector": "each_other_opponent"})],
                    [EffectSpec("impulsive_draw", {"count": 1, "same_turn_only": True})],
                ],
                "descriptions": [
                    "Zerstöre ein Artefakt dieses Gegners.",
                    "Parapet Thrasher fügt jedem anderen Gegner 4 Schaden zu.",
                    "Exiliere die oberste Karte deiner Bibliothek. Du darfst sie in diesem Zug spielen.",
                ],
            },
        ),
    ]


register("Parapet Thrasher", _parapet_thrasher)
