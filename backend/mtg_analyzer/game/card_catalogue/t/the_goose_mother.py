from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_goose_mother() -> list[AbilitySpec]:
    """Flying
    The Goose Mother enters with X +1/+1 counters on it.
    When The Goose Mother enters, create half X Food tokens, rounded up.
    Whenever The Goose Mother attacks, you may sacrifice a Food. If you do,
    draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": "half_x_up", "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "Sacrifice a Food",
                "effects": [{"type": "draw", "params": {"count": 1}}],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("The Goose Mother", _the_goose_mother)
