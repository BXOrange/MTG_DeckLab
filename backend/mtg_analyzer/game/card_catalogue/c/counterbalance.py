from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _counterbalance() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may reveal the top card of
    your library. If you do, counter that spell if it has the same mana
    value as the revealed card.

    — MEC-41. ENG-37 B5: `reveal_top` stashes the top card as the
    `revealed` referent, then `if_else` gates on `amount_compare`
    (revealed card's mana value == the firing `SPELL_CAST` event's own
    ``mana_value`` — the new `trigger_event` `effect_amounts` kind) and,
    when it matches, `counter` the triggering spell
    (``target_from_trigger_event="instance_id"``) so RULE 118 "can't be
    countered" is still honoured. "You may reveal" is a documented
    simplification to unconditional, as in the retired fused effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "reveal_top", "params": {"whose": "you"}},
                {"type": "if_else", "params": {
                    "condition": {"kind": "amount_compare", "op": "eq",
                                  "left": {"kind": "characteristic",
                                           "characteristic": "mana_value", "of": "revealed"},
                                  "right": {"kind": "trigger_event", "field": "mana_value"}},
                    "then": [{"type": "counter",
                              "params": {"target_from_trigger_event": "instance_id"}}],
                    "else": [],
                }},
            ]})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
            },
        ),
    ]


register("Counterbalance", _counterbalance)
