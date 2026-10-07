from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Printed thresholds.
_MIN_CAST_MANA_VALUE = 5
_MANA_VALUE_OFFSET = 4
_HASTE_COUNTERS = 3


def _runadi_behemoth_caller() -> list[AbilitySpec]:
    """Whenever you cast a creature spell with mana value 5 or greater, that
    creature enters with X additional +1/+1 counters on it, where X is its mana
    value minus 4.
    Creatures you control with three or more +1/+1 counters on them have haste.
    {T}: Add {G}.

    — PLAY-ALL (Hydranten). The cast trigger is respondable and grants entry
    counters to the triggering spell's stack incarnation. Its amount uses
    the announced mana value, including X; the grant survives Runadi leaving
    the battlefield. The haste static checks three or more +1/+1 counters.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_entry_counters_to_triggering_spell", {
                "kind": "+1/+1", "mana_value_minus": _MANA_VALUE_OFFSET,
            })],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "you"},
                     "spell_filter": {"card_type": "creature"},
                     "spell_mana_value_at_least": _MIN_CAST_MANA_VALUE},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "keywords": ["haste"],
                "object_filter": {"has_counter_kind": "+1/+1", "counter_min": _HASTE_COUNTERS},
            })],
        ),
    ]


register("Runadi, Behemoth Caller", _runadi_behemoth_caller)
