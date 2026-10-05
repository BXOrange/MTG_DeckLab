from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pyreswipe_hawk() -> list[AbilitySpec]:
    """Flying, haste
    Whenever this creature attacks, it gets +X/+0 until end of turn, where X is the greatest mana
    value among artifacts you control.
    Whenever you expend 6, gain control of up to one target artifact for as long as you control this
    creature. (You expend 6 as you spend your sixth total mana to cast spells during a turn.)

    — Animated Army deck batch. Flying/haste are keywords. The pump is the Pathbreaker Ibex shape
    with the ``greatest_mana_value_among_artifacts_you_control`` selector (the PAR-80 "greatest
    `<metric>` among `<scope>`" reader gained an ``artifacts`` scope), power only. The expend trigger
    is the parser's own head (`EXPEND`, ``filter.amount == 6``) with a `grant_until` layer-2
    ``control_change`` bounded by ``for_as_long_as ~ is on the battlefield``. **Documented
    simplification:** "for as long as you control this creature" is checked as the Hawk staying on
    the battlefield — if an opponent steals the Hawk itself, the artifact follows its new controller.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "amount_from_count_selector": "greatest_mana_value_among_artifacts_you_control",
                "amount_from_count_selector_axis": "power",
                "selector": None, "trigger_subject": False, "target_kind": None,
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "static": {"type": "control_change", "params": {}},
                "target_kind": "artifact", "optional": True,
                "condition": {"kind": "source_on_battlefield"},
            })],
            trigger={"event": EventType.EXPEND, "condition": {"subject": "you"}, "filter": {"amount": 6}},
        ),
    ]


register("Pyreswipe Hawk", _pyreswipe_hawk)
