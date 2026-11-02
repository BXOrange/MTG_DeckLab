from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _champion_of_lambholt() -> list[AbilitySpec]:
    """Creatures with power less than this creature's power can't block creatures you control.
    Whenever another creature you control enters, put a +1/+1 counter on this creature.

    The restriction is Graaz's ``combat_restriction`` ``cant_be_blocked_by`` over creatures you control (RULE
    509.1b); its filter's ``power_lt_source_power`` is resolved at stamp time against this creature's freshly
    derived power (`source_relative_filter`), so the threshold follows its +1/+1 counters. The trigger is
    Runaway Steam-Kin's self ``add_counters``.
    """
    return [
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            "kind": "cant_be_blocked_by", "affects": "creatures_you_control",
            "filter": {"power_lt_source_power": True},
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": None})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": True,
                              "filter": {"card_type": "creature"}},
            },
        ),
    ]


register("Champion of Lambholt", _champion_of_lambholt)
