from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_wandering_emperor() -> list[AbilitySpec]:
    """Flash
    As long as The Wandering Emperor entered this turn, you may activate
    her loyalty abilities any time you could cast an instant.
    +1: Put a +1/+1 counter on up to one target creature. It gains first
    strike until end of turn.
    −1: Create a 2/2 white Samurai creature token with vigilance.
    −2: Exile target tapped creature. You gain 2 life.

    — The Wandering Emperor. Flash comes from the RULE 702 keyword
    catalogue (and is now honoured for casting timing). The "activate
    loyalty abilities at instant speed" clause is now real too
    (`conditional_flash={"entered_this_turn": True}`, `game/
    condition_query.py`/`GameEngine._can_activate_loyalty`) — carried on
    the first loyalty ability below; `effect_binder.attach_to_object` scans
    every spec for it regardless of which one carries it, same as
    `additional_cost`. −2 drops the "tapped" restriction on its target (no
    such target filter exists yet).
    """
    return [
        AbilitySpec(
            "activated",
            [
                # ENG-37 B4: one "up to one target creature" (the counter
                # clause), reused by `grant_until`'s ``previous_subject``
                # pronoun for "It gains first strike until end of turn."
                # instead of the fused ``add_counter_first_strike``.
                EffectSpec("add_counters", {
                    "kind": "+1/+1", "amount": 1,
                    "target_kind": "creature", "optional": True,
                }),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "grant_keyword", "params": {"keywords": ["first_strike"]}},
                }),
            ],
            cost={"loyalty": 1},
            conditional_flash={"entered_this_turn": True},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "token_name": "Samurai", "power": 2, "toughness": 2, "count": 1,
                "colors": ["W"], "subtypes": ["Samurai"], "keywords": ["vigilance"],
            })],
            cost={"loyalty": -1},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "creature"}),
                EffectSpec("gain_life", {"amount": 2}),
            ],
            cost={"loyalty": -2},
        ),
    ]


register("The Wandering Emperor", _the_wandering_emperor)
