from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shalai_voice_of_plenty() -> list[AbilitySpec]:
    """Flying
    You, planeswalkers you control, and other creatures you control have
    hexproof.
    {4}{G}{G}: Put a +1/+1 counter on each creature you control.

    — PLAY-ALL Step 2 (SpongeBob). Flying is a printed keyword; the {4}{G}{G}
    counters ability is the parser's own claim, reproduced. The hexproof
    sentence is three grants: **you** (the new `player_hexproof` static,
    `continuous.player_has_hexproof`, which `targeting.legal_targets` applies to
    an opponent's player targeting — the first player-hexproof in the engine),
    **planeswalkers you control** (`grant_keyword` over ``permanents_you_control``
    narrowed by ``card_type: planeswalker``) and **other creatures you control**
    (the parser's own ``other_creatures_you_control`` grant).
    """
    return [
        AbilitySpec("static", [EffectSpec("player_hexproof", {})]),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "permanents_you_control", "object_filter": {"card_type": "planeswalker"},
                "keywords": ["hexproof"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "other_creatures_you_control", "keywords": ["hexproof"]})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"kind": "+1/+1", "selector": "each_creature_you_control", "count": 1})],
            cost={"text": "{4}{G}{G}"},
        ),
    ]


register("Shalai, Voice of Plenty", _shalai_voice_of_plenty)
