from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grenzo_havoc_raiser() -> list[AbilitySpec]:
    """Whenever a creature you control deals combat damage to a player, choose one —
    • Goad target creature that player controls.
    • Exile the top card of that player's library. Until end of turn, you may cast that card and you may spend mana as though it were mana of any color to cast that spell.

    — PLAY-ALL (Mardu Surge). The modal combat-damage trigger either
    goads a creature of the damaged player or exiles their top library card.
    The same-turn permission permits casting spells, excluding land plays
    and modal land faces, with mana of any color.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "controller": "you", "type": "creature"},
                "filter": {"combat": True, "is_player": True},
            },
            modes={
                "options": [
                    [EffectSpec("goad", {"target_kind": "creature_that_player_controls"})],
                    [EffectSpec("impulsive_draw", {
                        "count": 1, "same_turn_only": True, "library_of": "that_player",
                        "mana_wildcard": "color",
                        "only_spells": True,
                    })],
                ],
                "descriptions": [
                    "Reize eine Zielkreatur dieses Spielers an.",
                    "Verbanne die oberste Karte der Bibliothek dieses Spielers; du darfst sie bis zum Ende des "
                    "Zuges wirken und dafür Mana beliebiger Farbe ausgeben.",
                ],
            },
        ),
    ]


register("Grenzo, Havoc Raiser", _grenzo_havoc_raiser)
