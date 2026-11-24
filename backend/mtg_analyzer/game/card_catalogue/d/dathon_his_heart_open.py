from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dathon_his_heart_open() -> list[AbilitySpec]:
    """Whenever you cast an enchantment spell, draw a card. If it's a Saga spell, Dathon deals 2 damage to each opponent.
    {2}: Choose a counter on target enchantment you control. Put another counter of that kind on it. Activate only as a sorcery.
    """
    return [
        AbilitySpec("triggered", [EffectSpec("draw", {"count": 1}),
            EffectSpec("damage", {"amount": 2, "selector": "each_opponent"},
                condition={"kind": "trigger_event_object", "subtype": "saga"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group", "controller": "you"},
                     "spell_card_types": ["enchantment"]}),
        AbilitySpec("activated", [EffectSpec("add_counters", {"amount": 1,
            "target_kind": "enchantment_you_control", "choose_existing_kind": True})],
            cost={"text": "{2}", "sorcery_speed_only": True}),
    ]


register("Dathon, His Heart Open", _dathon_his_heart_open)
