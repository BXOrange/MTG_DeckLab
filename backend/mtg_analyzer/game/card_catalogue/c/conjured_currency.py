from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _conjured_currency() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you may exchange control of this
    enchantment and target permanent you neither own nor control.

    — The new `permanent_you_neither_own_nor_control` target kind
    (`targeting.legal_targets`); the self+target `ExchangeControlEffect`
    mode (`target_kind` only, no `first_target_kind`) Avarice Totem-shaped
    cards already use.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control", {
                "target_kind": "permanent_you_neither_own_nor_control",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            optional=True,
        ),
    ]


register("Conjured Currency", _conjured_currency)
