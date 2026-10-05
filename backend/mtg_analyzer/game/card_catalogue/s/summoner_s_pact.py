from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _summoners_pact() -> list[AbilitySpec]:
    """Search your library for a green creature card, reveal it, put it into
    your hand, then shuffle.
    At the beginning of your next upkeep, pay {2}{G}{G}. If you don't, you
    lose the game.

    — Summoner's Pact. Needed **nothing new**: `CreateDelayedTriggerEffect`
    (RULE 603.7) has named "the Pacts" in its docstring since it was built,
    and wave 2's `pay_cost_then` supplies the missing half — the *mandatory*
    payment with a consequence. The Pact is simply `pay_cost_then` with an
    empty "if you do" branch and `lose_game` as the "if you don't" one,
    which is exactly how the card reads.

    A player who *can't* afford the payment is never asked and loses
    immediately — the same "don't stall on a choice nobody can act on"
    shortcut ward and "sacrifice ~ unless you pay" already take, and here it
    is also the correct outcome.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature", "color": "G"},
                    "destination": "hand",
                    "count": 1,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Summoner's Pact: {2}{G}{G} bezahlen oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{2}{G}{G}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
        ),
    ]


register("Summoner's Pact", _summoners_pact)
