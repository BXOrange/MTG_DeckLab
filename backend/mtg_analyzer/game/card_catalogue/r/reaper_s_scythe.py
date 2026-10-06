from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _reaper_s_scythe() -> list[AbilitySpec]:
    """Job select
    At the beginning of your end step, put a soul counter on this Equipment for each player who lost life this turn.
    Equipped creature gets +1/+1 for each soul counter on this Equipment and is an Assassin in addition to its other types.
    Death Sickle — Equip {2}

    — PLAY-ALL (Scions & Spellcraft). Job select and Equip are keywords. The end-step trigger measures the new
    ``players_who_lost_life_this_turn`` count selector; the static is the parser's ``source_soul_counters`` anthem plus the Assassin `type_change`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": {"kind": "count_selector", "selector": "players_who_lost_life_this_turn"}, "kind": "soul",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "attached_permanent", "power": 1, "toughness": 1,
                    "power_count": "source_soul_counters", "toughness_count": "source_soul_counters",
                }),
                EffectSpec("type_change", {"affects": "attached_permanent", "add_subtypes": ["Assassin"]}),
            ],
        ),
    ]


register("Reaper's Scythe", _reaper_s_scythe)
