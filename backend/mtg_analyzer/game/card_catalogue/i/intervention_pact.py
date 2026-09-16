from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _intervention_pact() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. You gain life equal to the damage prevented
    this way.
    At the beginning of your next upkeep, pay {1}{W}{W}. If you don't, you
    lose the game.

    — The delayed pay-or-lose clause is Pact of Negation's own template
    (``create_delayed_trigger``/``pay_cost_then``); see that entry's
    docstring for why it needed no new primitive.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("request_prevent_damage_source", {
                    "amount": "all",
                    "rider": {"kind": "gain_life", "recipient": "you"},
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Interventionspakt: {1}{W}{W} bezahlen "
                                    "oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{1}{W}{W}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
        ),
    ]


register("Intervention Pact", _intervention_pact)
