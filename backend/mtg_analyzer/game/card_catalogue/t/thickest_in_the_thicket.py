from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thickest_in_the_thicket() -> list[AbilitySpec]:
    """When this enchantment enters, put X +1/+1 counters on target creature, where X is that
    creature's power.
    At the beginning of your end step, draw two cards if you control the creature with the greatest
    power or tied for the greatest power.

    — Animated Army deck batch. The ETB is `add_counters` whose count is the target's own power
    (the ``characteristic`` operand, ``of: "target"``). The end-step draw is Yavimaya Bloomsage's
    phase-trigger head with the new ``controls_greatest_power_creature`` condition, checked both
    when the trigger would fire and on resolution (RULE 603.4's intervening "if").
    """
    gate = {"kind": "controls_greatest_power_creature"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "target_kind": "creature", "kind": "+1/+1",
                "count": {"kind": "characteristic", "characteristic": "power", "of": "target"},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 2}, condition=gate)],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you", "active_if": gate},
        ),
    ]


register("Thickest in the Thicket", _thickest_in_the_thicket)
