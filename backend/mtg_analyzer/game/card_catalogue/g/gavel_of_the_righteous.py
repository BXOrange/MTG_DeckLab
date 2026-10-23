from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gavel_of_the_righteous() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, put a charge counter on this Equipment.
    Equipped creature gets +1/+1 for each counter on this Equipment.
    As long as this Equipment has four or more counters on it, equipped creature has double strike.
    Equip—Pay {3} or remove a counter from this Equipment.

    Represent the two payments as separate Equip options, sharing the existing
    RULE 702.6a targeting, timing and attachment behavior. Both the bonus and
    threshold count every kind of counter, not just charge counters.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "charge"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "total_counters_on_source", "toughness_count": "total_counters_on_source",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "attached_permanent", "keywords": ["double_strike"],
                "active_if": {"kind": "source_counters", "min": 4},
            })],
        ),
        AbilitySpec("keyword", [], keyword={"name": "equip", "cost": "{3}"}, raw_text="Equip—Pay {3}"),
        AbilitySpec("keyword", [], keyword={"name": "equip", "cost": "Remove a counter from ~"},
                    raw_text="Equip—Remove a counter from this Equipment"),
    ]


register("Gavel of the Righteous", _gavel_of_the_righteous)
