
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _synchronized_charge() -> list[AbilitySpec]:
    'Distribute two +1/+1 counters among one or two target creatures you control. Creatures you control with counters on them gain vigilance and trample until end of turn.\nHarmonize {4}{G} (You may cast this card from your graveyard for its harmonize cost. You may tap a creature you control to reduce that cost by {X}, where X is its power. Then exile this spell.)'
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("add_counters", {"amount": 2, "target_kind": "creature_you_control", "target_count": 1, "target_count_max": 2, "divided": True}),
            EffectSpec("pump", {"selector": "creatures_you_control", "creature_filter": {"has_counter": True}, "keywords": ["vigilance", "trample"]}),
        ]),
    ]


register('Synchronized Charge', _synchronized_charge)
