from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _arteeoh_dread_scavenger() -> list[AbilitySpec]:
    """Flying, deathtouch
    Whenever Arteeoh deals combat damage to a player, you may exchange
    control of two other target artifacts. When you do, create a token
    that's a copy of target artifact you don't control, except it's a 1/1
    green Squirrel creature token in addition to its other colors and
    types.

    — See `ExchangeControlThenCopyTokenEffect`'s own docstring for the
    exchange + RULE 603.11 reflexive copy-token connector and its
    documented colour-addition simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control_then_copy_token", {})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
            optional=True,
        ),
    ]


register("Arteeoh, Dread Scavenger", _arteeoh_dread_scavenger)
