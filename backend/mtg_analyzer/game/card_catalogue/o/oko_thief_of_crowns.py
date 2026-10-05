from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _oko_thief_of_crowns() -> list[AbilitySpec]:
    """+2: Create a Food token.
    +1: Target artifact or creature loses all abilities and becomes a
    green Elk creature with base power and toughness 3/3.
    -5: Exchange control of target artifact or creature you control and
    target creature an opponent controls with power 3 or less.

    — MEC-43 round 4E. "+2" is a plain Food token creation, the same
    ``create_token`` shape every other Food-maker in this cache already
    uses. "+1" is the already-shipped Elk template (Kenrith's
    Transformation) reused resolve-time — two chained ``grant_until``
    effects at ``duration="rest_of_game"`` (Vraska, Betrayal's Sting's own
    ``-2`` established this exact "permanent characteristic overwrite via
    a resolve-time grant, not a `temp_*` pump" idiom), the second reusing
    the first's own target via ``previous_subject`` so only one RULE 115
    target is asked for both clauses.

    "-5" needed `ExchangeControlEffect` widened into a genuine **two-
    target** mode (``first_target_kind``/``second_creature_filter``, via
    `GameEffect.extra_target_specs`): unlike Gilded Drake/Volatile
    Stormdrake (always "this creature and up to one target creature" —
    one side is the ability's own source), *both* sides here are
    independently-chosen targets, neither optional (Oko's own text prints
    no "up to"/failure clause). The first target's own kind
    (``artifact_or_creature_you_control``) and the second's own qualifier
    (``creature_you_dont_control`` + ``creature_filter={"max_power": 3}``)
    both needed small `targeting.py` additions — a controller-scoped
    "artifact or creature" union kind (mirroring `creature_or_
    planeswalker_you_control`'s identical shape for its own pair), and
    `creature_you_dont_control` honouring `TargetSpec.creature_filter` at
    all (every existing caller of that kind never set one, so this is
    purely additive).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "target_kind": "artifact_or_creature", "duration": "rest_of_game",
                    "static": {"type": "remove_all_abilities", "params": {}},
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {
                        "type": "type_change",
                        "params": {
                            "add_types": ["creature"], "set_subtypes": ["Elk"],
                            "power": 3, "toughness": 3,
                        },
                    },
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "color_change", "params": {"colors": ["G"], "set": True}},
                }),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_control", {
                "first_target_kind": "artifact_or_creature_you_control",
                "target_kind": "creature_you_dont_control",
                "second_creature_filter": {"max_power": 3},
            })],
            cost={"loyalty": -5},
        ),
    ]


register("Oko, Thief of Crowns", _oko_thief_of_crowns)
