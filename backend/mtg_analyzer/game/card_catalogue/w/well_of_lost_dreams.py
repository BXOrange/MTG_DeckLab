from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _well_of_lost_dreams() -> list[AbilitySpec]:
    """Whenever you gain life, you may pay {X}, where X is less than or equal to the amount of life you gained. If you do, draw X cards.

    — PLAY-ALL (Hope to the last). A life-gain trigger over `pay_cost_then` with an ``{X}`` mana cost (ENG-48's
    announced-X payment) whose largest offered X is capped by the event's ``amount`` (``x_cap_from_trigger_event``).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{x}", "x_cap_from_trigger_event": "amount",
                "effects": [{"type": "draw", "params": {"count": "x"}}],
            })],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
    ]


register("Well of Lost Dreams", _well_of_lost_dreams)
