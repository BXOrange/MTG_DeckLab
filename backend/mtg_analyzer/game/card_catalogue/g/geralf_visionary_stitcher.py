from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _geralf_visionary_stitcher() -> list[AbilitySpec]:
    """Zombies you control have flying.
    {U}, {T}, Sacrifice another nontoken creature: Create an X/X blue Zombie creature token, where X is the
    sacrificed creature's toughness.

    — The flying static is the parser's own claim, reproduced. The activated ability is Altar of Dementia's
    sacrifice-cost stamp: the cost (RULE 602.2b, "another nontoken creature" -- never Geralf himself) records the
    victim's last-known toughness (RULE 608.2h) as ``sacrificed_cost_toughness``, which `create_token`'s ``pt_amount``
    operand (a `count_selector`) reads on resolution to size the X/X Zombie.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": 'creatures_you_control', "subtype": 'Zombie', "keywords": ['flying']})],
            raw_text='zombies you control have flying.',
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "colors": ["U"], "subtypes": ["Zombie"], "token_name": "Zombie",
                "pt_amount": {"kind": "count_selector", "selector": "sacrificed_cost_toughness"},
            })],
            cost={"text": "{U}, {T}, Sacrifice another nontoken creature"},
            raw_text="{u}, {t}, sacrifice another nontoken creature: create an x/x blue zombie creature token, where x is the sacrificed creature's toughness.",
        ),
    ]


register('Geralf, Visionary Stitcher', _geralf_visionary_stitcher)
