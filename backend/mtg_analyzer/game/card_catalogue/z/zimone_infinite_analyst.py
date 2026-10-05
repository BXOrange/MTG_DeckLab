from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Quandrix "your first spell with {X} in its mana cost each turn"
# ===========================================================================
# Engine: `GameState.cast_x_spell_this_turn` per-turn set + `SPELL_CAST`
# ``first_x_spell`` flag + binder predicate ``first_x_spell``; count_selector
# ``study_counters_on_source``.


def _zimone_infinite_analyst() -> list[AbilitySpec]:
    """The first spell you cast with {X} in its mana cost each turn costs {1}
    less to cast for each +1/+1 counter on Zimone.
    Whenever you cast your first spell with {X} in its mana cost each turn,
    put two +1/+1 counters on Zimone.

    Documented simplification: the per-counter cost reduction on that first
    {X} spell is not modeled — only the +1/+1 counter payoff."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 2, "kind": "+1/+1"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "first_x_spell": True,
            },
        ),
    ]


register("Zimone, Infinite Analyst", _zimone_infinite_analyst)
