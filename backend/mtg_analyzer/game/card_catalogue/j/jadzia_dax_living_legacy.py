from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jadzia_dax_living_legacy() -> list[AbilitySpec]:
    """At the beginning of your first main phase, put a +1/+1 counter on Jadzia Dax, then add an amount of {G} equal to the number of counters on her.
    Transfer Symbiont — {2}{G}, Discard this card: Put two +1/+1 counters on target creature.

    RULE 106.1 / 122.1: the mana is sized by every counter on her after the
    new one lands (``counters_on`` sums all kinds); it empties at the end
    of the phase like any mana (RULE 500.5).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}),
                EffectSpec("add_mana", {"color": "G", "amount_selector": {"counters_on": "source"}}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main1"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"count": 2, "kind": "+1/+1", "target_kind": "creature"})],
            cost={"text": "{2}{g}, discard this card"},
        ),
    ]


register("Jadzia Dax, Living Legacy", _jadzia_dax_living_legacy)
