from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grenzo_havoc_raiser() -> list[AbilitySpec]:
    """Whenever a creature you control deals combat damage to a player, choose one —
    • Goad target creature that player controls.
    • Exile the top card of that player's library. Until end of turn, you may cast that card and you may spend mana as though it were mana of any color to cast that spell.

    — Grenzo, Havoc Raiser. A modal trigger (RULE 700.2) on the per-creature combat `DAMAGE` event. "That player"
    is the damaged player: the goad's target is the existing `creature_that_player_controls` kind (Popular
    Entertainer's), and the exile is `impulsive_draw` with the new ``library_of="that_player"`` (Ragavan's exile
    from the damaged player's library, but for any creature of ours) plus Mezzio Mugger's ``mana_wildcard="color"``.
    **Documented simplification:** the permission is the generic "play this turn" one, so an exiled land could also
    be played, where the card says only "cast".
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
