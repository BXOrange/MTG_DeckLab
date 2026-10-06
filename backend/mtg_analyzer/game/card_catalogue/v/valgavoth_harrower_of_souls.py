from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _valgavoth_harrower_of_souls() -> list[AbilitySpec]:
    """Flying
    Ward—Pay 2 life.
    Whenever an opponent loses life for the first time during each of their turns, put a +1/+1 counter on Valgavoth and draw a card.

    — PLAY-ALL (Endless Punishment). Flying and Ward are keywords. The head is a `LIFE_LOST` group trigger over an opponent, limited to once each turn (``limit``) and gated
    by the new ``controllers_turn`` predicate (the mirror of ``not_controllers_turn``: the player losing life must be the active player), i.e. the first loss
    during that opponent's own turn.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}), EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.LIFE_LOST, "condition": {"subject": "group", "controller": "opponent"},
                "limit": True, "controllers_turn": True,
            },
        ),
    ]


register("Valgavoth, Harrower of Souls", _valgavoth_harrower_of_souls)
