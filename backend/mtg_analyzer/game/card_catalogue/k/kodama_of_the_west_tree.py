from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kodama_of_the_west_tree() -> list[AbilitySpec]:
    """Reach
    Modified creatures you control have trample. (Equipment, Auras you
    control, and counters are modifications.)
    Whenever a modified creature you control deals combat damage to a
    player, search your library for a basic land card, put it onto the
    battlefield tapped, then shuffle.

    — PLAY-ALL Step 2 (Hydranten). The trample grant is the parser's own
    claim, reproduced verbatim (Reach is a printed keyword, recognized from
    the card). The trigger is the parser's "whenever a creature you control
    deals combat damage to a player" group shape — ``search`` for a basic
    land to ``battlefield_tapped`` — with the group filter narrowed by the
    same ``modified`` key the grant uses.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "object_filter": {"modified": True},
                "keywords": ["trample"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"basic": True}, "destination": "battlefield_tapped"})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {
                    "subject": "group", "controller": "you", "other": False,
                    "filter": {"card_type": "creature", "modified": True},
                },
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Kodama of the West Tree", _kodama_of_the_west_tree)
