from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _form(types: list[str], size: int, condition=None) -> EffectSpec:
    return EffectSpec("grant_until", {
        "static": {"type": "type_change", "params": {
            "affects": "self", "set_creature_types": types,
        }},
        "duration": "rest_of_game", "self_subject": True, "target_kind": None,
        "extra_statics": [{"type": "pt_set", "params": {
            "power": size, "toughness": size, "affects": "self",
        }}],
    }, condition=condition)


def _evolved_sleeper() -> list[AbilitySpec]:
    """{B}: This creature becomes a Human Cleric with base power and toughness 2/2.
    {1}{B}: If this creature is a Cleric, put a deathtouch counter on it and it becomes a Phyrexian Human Cleric with base power and toughness 3/3.
    {1}{B}{B}: If this creature is a Phyrexian, put a +1/+1 counter on it, then you draw a card and you lose 1 life.
    """
    cleric = {"kind": "is_subtype", "subtype": "cleric"}
    phyrexian = {"kind": "is_subtype", "subtype": "phyrexian"}
    return [
        AbilitySpec("activated", [_form(["Human", "Cleric"], 2)], cost={"text": "{B}"}),
        AbilitySpec("activated", [
            EffectSpec("add_counters", {"kind": "deathtouch", "count": 1}, condition=cleric),
            _form(["Phyrexian", "Human", "Cleric"], 3, condition=cleric),
        ], cost={"text": "{1}{B}"}),
        AbilitySpec("activated", [
            EffectSpec("add_counters", {"kind": "+1/+1", "count": 1}, condition=phyrexian),
            EffectSpec("draw", {"count": 1}, condition=phyrexian),
            EffectSpec("lose_life", {"amount": 1}, condition=phyrexian),
        ], cost={"text": "{1}{B}{B}"}),
    ]


register("Evolved Sleeper", _evolved_sleeper)
