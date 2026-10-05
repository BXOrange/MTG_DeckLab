from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# attack-trigger P/T match, mass keyword strip, end-step exile+token
# ===========================================================================


def _tanazir_quandrix() -> list[AbilitySpec]:
    """Flying, trample
    When Tanazir Quandrix enters, double the number of +1/+1 counters on
    target creature you control.
    Whenever Tanazir Quandrix attacks, you may have the base power and
    toughness of other creatures you control become equal to Tanazir
    Quandrix's power and toughness until end of turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("double_counters_on_target", {
                "target_kind": "creature_you_control", "kind": "+1/+1",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {"type": "pt_cda", "params": {
                    "affects": "other_creatures_you_control",
                    "power_count": "source_power", "toughness_count": "source_toughness",
                }},
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            optional=True,
        ),
    ]


register("Tanazir Quandrix", _tanazir_quandrix)
