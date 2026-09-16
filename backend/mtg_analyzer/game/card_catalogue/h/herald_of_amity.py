from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _herald_of_amity() -> list[AbilitySpec]:
    """Flying
    When this creature enters, exile the top eight cards of your library. You
    may cast an Aura spell from among them without paying its mana cost. Then
    put the rest on the bottom of your library in a random order.
    Whenever this creature attacks, it gets +X/+X until end of turn, where X
    is the number of Auras you control.

    Documented simplification: the ETB is modeled with
    ``draw_reveal_cast_one_free`` (count 8) — the eight cards go to hand
    rather than being exiled/bottomed, and the free cast is not narrowed to
    an Aura. The attack pump ("+X/+X where X is the number of Auras you
    control") is modeled via a per-count anthem pump on ``self``."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw_reveal_cast_one_free", {"count": 8})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 1, "toughness": 1,
                "amount_from_count_selector": "auras_you_control",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Herald of Amity", _herald_of_amity)
