from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _llawan_cephalid_empress() -> list[AbilitySpec]:
    """When Llawan enters, return all blue creatures your opponents
    control to their owners' hands.
    Your opponents can't cast blue creature spells.

    — MEC-43. The ETB is `ReturnToHandEffect`'s new ``"opponents_
    creatures"`` mass selector (the opponent-scoped sibling of the existing
    ``"all_creatures"``) combined with its also-new ``filter={"color":
    "U"}``; the static is `cast_prohibition`'s new ``color``/
    ``creature_only`` combination (MEC-43's first card needing both a
    card-type and a colour restriction on the same clause).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {
                "selector": "opponents_creatures", "filter": {"color": "U"},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents", "creature_only": True, "color": "U",
            })],
        ),
    ]


register("Llawan, Cephalid Empress", _llawan_cephalid_empress)
