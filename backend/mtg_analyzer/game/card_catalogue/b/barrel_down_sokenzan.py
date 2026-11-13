"""Barrel Down Sokenzan."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _barrel_down_sokenzan():
    """Sweep — Return any number of Mountains you control to their owner's hand. Barrel Down Sokenzan deals damage to target creature equal to twice the number of Mountains returned this way."""
    return [AbilitySpec("spell_effect", [
        EffectSpec("mark_event_log", {}),
        EffectSpec("choose_objects", {
            "action": "return_to_hand", "what": "permanent", "count": "all", "optional": True,
            "permanent_filter": {"subtype": "mountain"},
        }),
        EffectSpec("bind", {
            "name": "n", "amount": {"kind": "this_way_count", "pool": "returned", "multiply": 2},
            "effects": [{"type": "damage", "params": {"amount": "$n", "target_kind": "creature"}}],
        }),
    ])]


register("Barrel Down Sokenzan", _barrel_down_sokenzan)
