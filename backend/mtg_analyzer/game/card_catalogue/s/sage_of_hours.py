from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...costs import REMOVE_COUNTERS_ALL
from ...card_registry.core import register


def _sage_of_hours() -> list[AbilitySpec]:
    """Heroic — Whenever you cast a spell that targets this creature, put a
    +1/+1 counter on it.
    Remove all +1/+1 counters from this creature: For each five counters
    removed this way, take an extra turn after this one.

    — PAR-67. Heroic's own trigger is the parser's ordinary "whenever you
    cast a spell that targets ~" shape (`requires_spell_targets_source`) —
    reproduced here rather than left to the fallback, since registering a
    card replaces its *entire* parser reading, not just the clause that
    failed. The activated ability is the new shape: a mandatory "remove
    all `<kind>` counters" **cost** (`costs.REMOVE_COUNTERS_ALL` — distinct
    from `REMOVE_COUNTERS_ANY`, which is the payer's own free choice of
    amount), stamping how many it actually removed onto the source
    (`GameObject.counters_removed_as_cost`, the cost-paid sibling of
    `x_paid` — a cost has no resolving `GameContext` for the ordinary
    "counters removed this way" tally to land in). The effect reads that
    stamp back through a `bind` (RULE 608.2) with a ``divide=5`` amount,
    scaling `TakeExtraTurnEffect`'s own ``count``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={
                "event": "SPELL_CAST", "condition": {"subject": "you"},
                "requires_spell_targets_source": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "counters_removed_as_cost", "divide": 5},
                "effects": [{"type": "take_extra_turn", "params": {"count": "$n"}}],
            })],
            cost={"remove_counters": ("+1/+1", REMOVE_COUNTERS_ALL)},
        ),
    ]


register("Sage of Hours", _sage_of_hours)
