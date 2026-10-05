from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eshki_temur_s_roar() -> list[AbilitySpec]:
    """Whenever you cast a creature spell, put a +1/+1 counter on this creature. If that spell's power is 4 or greater, draw a card. If that spell's power is 6 or greater, this creature deals damage equal to its power to each opponent.

    — PLAY-ALL Step 2 (Temur Roar). A creature-spell cast trigger whose body is a `seq`: the counter first,
    then two `if_else` rungs reading the cast spell's printed power (`power` predicate on the `entering`
    referent — the firing event's own object, here the spell on the stack). The damage is a `bind` measuring
    *Eshki's* power (`of: "source"` — the shipped `subject_damages_each_opponent_equal_to_power` reads the
    firing object under a group trigger, i.e. the spell), taken after the counter is on.
    """
    def spell_power_at_least(value: int) -> dict:
        return {"kind": "power", "of": "entering", "min": value}

    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "add_counters", "params": {"kind": "+1/+1", "amount": 1, "target_kind": None}},
                {"type": "if_else", "params": {
                    "condition": spell_power_at_least(4),
                    "then": [{"type": "draw", "params": {"count": 1}}],
                    "else": [],
                }},
                {"type": "if_else", "params": {
                    "condition": spell_power_at_least(6),
                    "then": [{"type": "bind", "params": {
                        "name": "n",
                        "amount": {"kind": "characteristic", "characteristic": "power", "of": "source"},
                        "effects": [{"type": "damage", "params": {"amount": "$n", "selector": "each_opponent"}}],
                    }}],
                    "else": [],
                }},
            ]})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["creature"],
            },
        ),
    ]


register("Eshki, Temur's Roar", _eshki_temur_s_roar)
