
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smoldering_egg_ashmouth_dragon() -> list[AbilitySpec]:
    'Defender\nWhenever you cast an instant or sorcery spell, put a number of ember counters on this creature equal to the amount of mana spent to cast that spell. Then if this creature has seven or more ember counters on it, remove them and transform this creature.'
    return [
        AbilitySpec("triggered", [
            EffectSpec("add_counters", {"kind": "ember", "amount": {"kind": "trigger_event", "field": "mana_spent"}}),
            EffectSpec("if_else", {"condition": {"kind": "source_counters", "counter": "ember", "min": 7},
                "then": [{"type": "remove_counters", "params": {"self_only": True, "kind": "ember"}},
                         {"type": "transform", "params": {}}]}),
        ], trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"card_type_any": ["instant", "sorcery"]}}),
    ]


register('Smoldering Egg // Ashmouth Dragon', _smoldering_egg_ashmouth_dragon)
