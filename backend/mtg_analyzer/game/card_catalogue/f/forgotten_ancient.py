from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Forgotten Ancient (distribute counters) — PAR-60
# ===========================================================================
# New `move_all_plus_one_counters_from_self` effect (documented
# simplification: all counters onto one up-to-one target rather than RULE
# 122's per-counter distribution across several). The cast trigger re-adds
# the parser-claimed clause (a registered card turns parse_oracle off).


def _forgotten_ancient() -> list[AbilitySpec]:
    """Whenever a player casts a spell, you may put a +1/+1 counter on this
    creature.
    At the beginning of your upkeep, you may move any number of +1/+1
    counters from this creature onto other creatures."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("move_all_plus_one_counters_from_self", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
        ),
    ]


register("Forgotten Ancient", _forgotten_ancient)
