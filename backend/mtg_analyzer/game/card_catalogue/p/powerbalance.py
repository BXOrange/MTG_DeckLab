from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _powerbalance() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may reveal the top card of
    your library. If you do, you may cast that card without paying its
    mana cost if the two spells have the same mana value.

    — Powerbalance. ENG-37 B5, the free-cast sibling of Counterbalance:
    `seq([reveal_top, if_else(amount_compare(revealed mana value ==
    SPELL_CAST event's ``mana_value``), then=[cast_revealed_free],
    else=[])])`. The reveal is a documented simplification to
    unconditional; `cast_revealed_free` keeps the cast a genuine "you may"
    (`_request_choose_objects`' ``"cast_free"`` action, optional).
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
                    "then": [{"type": "cast_revealed_free", "params": {}}],
                    "else": [],
                }},
            ]})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Powerbalance", _powerbalance)
