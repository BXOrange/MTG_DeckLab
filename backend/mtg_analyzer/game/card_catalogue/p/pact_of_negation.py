from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pact_of_negation() -> list[AbilitySpec]:
    """Counter target spell.
    At the beginning of your next upkeep, pay {3}{U}{U}. If you don't, you
    lose the game.

    — Pact of Negation. Summoner's Pact's sibling; see that entry for why
    the delayed "pay or lose" needed no new primitive. Note the counter half
    was already parsed — only the Pact clause left the card `UNMODELED`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("counter", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Pact of Negation: {3}{U}{U} bezahlen oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{3}{U}{U}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
        ),
    ]


register("Pact of Negation", _pact_of_negation)
