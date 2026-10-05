from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _endurance() -> list[AbilitySpec]:
    """Flash. Reach. When this creature enters, up to one target player
    puts all the cards from their graveyard on the bottom of their library
    in a random order. Evoke—Exile a green card from your hand.

    — Endurance. Flash/Reach are keywords, already covered by the parser's
    keyword catalogue. A new `GraveyardToLibraryBottomRandomEffect` this
    batch (RULE 701.20-adjacent — randomizes only the moved batch's own
    relative order, leaving the rest of the library's order alone). MEC-65
    binds its printed exile-a-green-card Evoke cost through the shared RULE
    702.74 alternate-cast path.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("graveyard_to_library_bottom_random", {
                "target_kind": "player", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Endurance", _endurance)
