from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Nils, Discipline Enforcer (per-player end-step counter +
# per-attacker-variable counter attack tax) — PAR-60
# ===========================================================================
# Clause 1 is a new `nils_end_step_counters` effect (auto-picks each
# player's highest-power creature — documented simplification of "up to one
# target creature that player controls"). Clause 2 extends the existing
# `attack_tax` static with ``attacker_filter`` + ``amount_per_attacker_
# counter`` (each counter-bearing attacker pays its own counter count).


def _nils_discipline_enforcer() -> list[AbilitySpec]:
    """At the beginning of your end step, for each player, put a +1/+1
    counter on up to one target creature that player controls.
    Each creature with one or more counters on it can't attack you or
    planeswalkers you control unless its controller pays {X}, where X is the
    number of counters on that creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("nils_end_step_counters", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("attack_tax", {
                "attacker_filter": {"has_any_counter": True},
                "amount_per_attacker_counter": "any",
                "defender_scope": "player_or_planeswalker",
            })],
        ),
    ]


register("Nils, Discipline Enforcer", _nils_discipline_enforcer)
