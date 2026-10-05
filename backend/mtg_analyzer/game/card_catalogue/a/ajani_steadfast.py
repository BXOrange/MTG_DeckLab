from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ajani_steadfast() -> list[AbilitySpec]:
    """+1: Until end of turn, up to one target creature gets +1/+1 and
    gains first strike, vigilance, and lifelink.
    −2: Put a +1/+1 counter on each creature you control and a loyalty
    counter on each other planeswalker you control.
    −7: You get an emblem with "If a source would deal damage to you or a
    planeswalker you control, prevent all but 1 of that damage."

    — All three loyalty abilities are `UNCLAIMED` by the parser (not just
    the emblem the ticket had originally scoped) — `specs_for` trusts a
    registered card's specs wholesale, so all three need writing, the same
    Haazda Shield Mate lesson from Pass 2. +1 is an ordinary "up to one
    target" `pump` (The Wandering Emperor's own idiom). −2 is two
    `add_counters` specs in one ability — `selector="each_creature_you_
    control"` (already shipped) and the new `"each_other_planeswalker_you_
    control"` (MEC-30, `continuous.group_selector_objects`'s planeswalker-
    scoped sibling of ``other_creatures_you_control``). −7's emblem is the
    exact `prevent_damage` shape already execute-tested synthetically via
    the Hyperion test in `test_prevent_damage_family.py`.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "target_kind": "creature", "optional": True,
                "power": 1, "toughness": 1,
                "keywords": ["first strike", "vigilance", "lifelink"],
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"selector": "each_creature_you_control"}),
                EffectSpec("add_counters", {
                    "selector": "each_other_planeswalker_you_control", "kind": "loyalty",
                }),
            ],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {
                "ability": {
                    "ability_kind": "replacement",
                    "effects": [{
                        "type": "prevent_damage",
                        "params": {
                            "recipient_union": ["controller", {"card_type": "planeswalker"}],
                            "amount": {"all_but": 1},
                        },
                    }],
                },
            })],
            cost={"loyalty": -7},
        ),
    ]


register("Ajani Steadfast", _ajani_steadfast)
