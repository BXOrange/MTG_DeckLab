from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wick_the_whorled_mind() -> list[AbilitySpec]:
    """Whenever Wick or another Rat you control enters, create a 1/1 black
    Snail creature token if you don't control a Snail. Otherwise, put a
    +1/+1 counter on a Snail you control.
    {U}{B}{R}, Sacrifice a Snail: Wick deals damage equal to the sacrificed
    creature's power to each opponent. Then draw cards equal to the
    sacrificed creature's power.

    — PLAY-ALL Step 2 (Wick Snail Boom). The activated ability is the
    parser's own claim, reproduced verbatim. The trigger is the parser's
    "this creature or another Rat you control enters" head (``self_or_group``,
    ``subtypes: rat``, ``controller: you`` — Wick itself counts) over an `if_else` on ``controls_subtype: snail``:
    "otherwise" must be a real branch, not two independent gated clauses — the
    first clause would otherwise create the Snail and the second would
    immediately count it. The counter goes on "a Snail you
    control" via `add_counters` ``choose_one`` over a Snail group — the
    controller's pick at resolution, not a target (RULE 122.1), which also
    matters because an `if_else` branch cannot announce targets.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "controls_subtype", "subtype": "snail", "min": 1},
                "then": [{"type": "add_counters", "params": {
                    "count": 1, "kind": "+1/+1", "choose_one": True,
                    "group": {"zone": "battlefield", "of": "you", "filter": {"subtype": "snail"}},
                }}],
                "else": [{"type": "create_token", "params": {
                    "count": 1, "power": 1, "toughness": 1, "colors": ["B"],
                    "subtypes": ["Snail"], "keywords": [], "token_name": "Snail",
                }}],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "self_or_group", "controller": "you", "other": True,
                    "subtypes": ["rat"], "nontoken": False,
                },
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("bind", {
                    "name": "n",
                    "amount": {"kind": "count_selector", "selector": "sacrificed_cost_power"},
                    "effects": [{"type": "damage", "params": {"amount": "$n", "selector": "each_opponent"}}],
                }),
                EffectSpec("bind", {
                    "name": "n",
                    "amount": {"kind": "count_selector", "selector": "sacrificed_cost_power"},
                    "effects": [{"type": "draw", "params": {"count": "$n"}}],
                }),
            ],
            cost={"text": "{U}{B}{R}, Sacrifice a Snail"},
        ),
    ]


register("Wick, the Whorled Mind", _wick_the_whorled_mind)
