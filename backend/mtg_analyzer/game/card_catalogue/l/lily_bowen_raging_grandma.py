from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lily_bowen_raging_grandma() -> list[AbilitySpec]:
    """Vigilance
    Lily Bowen enters with two +1/+1 counters on it.
    At the beginning of your upkeep, double the number of +1/+1 counters on
    Lily Bowen if its power is 16 or less. Otherwise, remove all but one
    +1/+1 counter from it, then you gain 1 life for each +1/+1 counter
    removed this way.

    — PAR-67. Vigilance is a plain printed keyword; the ETB counters are
    already RULE 614.1-derived (`card_registry.entry_counters`, read
    straight off the card's oracle text regardless of registration — no
    spec needed here). The upkeep trigger is the new shape: an `if_else`
    (RULE 603.4) gated on the source's own derived power, whose "then"
    branch reuses `double_counters_on_target(mode="self")` (Primordial
    Hydra-shaped) unchanged, and whose "else" branch pairs a genuinely new
    `RemoveCountersEffect.keep` partial-removal count ("remove all but N",
    distinct from that effect's existing all-or-chosen-amount shapes) with
    `GainLifeEffect`'s pre-existing ``count_selector="counters_removed_
    this_way"`` reader (PAR-66) — no new life-gain wiring needed, only the
    partial removal that feeds it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "power", "max": 16},
                "then": [
                    {"type": "double_counters_on_target",
                     "params": {"mode": "self", "kind": "+1/+1"}},
                ],
                "else": [
                    {"type": "remove_counters",
                     "params": {"self_only": True, "kind": "+1/+1", "keep": 1}},
                    {"type": "gain_life",
                     "params": {"amount": 1, "count_selector": "counters_removed_this_way"}},
                ],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Lily Bowen, Raging Grandma", _lily_bowen_raging_grandma)
