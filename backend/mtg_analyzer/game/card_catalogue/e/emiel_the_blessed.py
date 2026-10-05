from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emiel_the_blessed() -> list[AbilitySpec]:
    """{3}: Exile another target creature you control, then return it to
    the battlefield under its owner's control.
    Whenever another creature you control enters, you may pay {G/W}. If
    you do, put a +1/+1 counter on it. If it's a Unicorn, put two +1/+1
    counters on it instead.

    — MEC-12 (cEDH staples). The activated ability is the plain
    `"blink"` `EffectSpec` (`BlinkEffect`, the same primitive Ephemerate/
    Restoration Angel use) with an explicit {3} cost, scoped to
    ``other_creature_you_control`` (targeting already excludes the source
    regardless — "another" needs no separate kind). The trigger is
    `pay_cost_then` wrapping `add_counters`'s ``trigger_subject_key``
    (targets whichever creature just entered — "it"), its count a `bind` over an `if`
    amount — 2 when the remembered creature is a Unicorn, else 1 — for "if it's a
    Unicorn, `<bigger effect>` instead".
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("blink", {"target_kind": "other_creature_you_control"})],
            cost={"mana": "{3}"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{G/W}",
                "remember_trigger_subject": True,
                "effects": [{
                    "type": "bind",
                    "params": {
                        "name": "n",
                        "amount": {
                            "kind": "if",
                            "condition": {"kind": "is_subtype", "subtype": "unicorn", "of": "remembered"},
                            "then": 2, "otherwise": 1,
                        },
                        "effects": [{"type": "add_counters", "params": {
                            "amount": "$n", "kind": "+1/+1", "trigger_subject_key": "remembered",
                        }}],
                    },
                }],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": True},
            },
        ),
    ]


register("Emiel the Blessed", _emiel_the_blessed)
