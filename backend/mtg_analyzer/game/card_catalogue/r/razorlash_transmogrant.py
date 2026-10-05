from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _razorlash_transmogrant() -> list[AbilitySpec]:
    """This creature can't block.
    {4}{B}{B}: Return this card from your graveyard to the battlefield with a +1/+1 counter on it. This ability costs {4} less to activate if an opponent controls four or more nonbasic lands.

    — PLAY-ALL Step 2 (Wretched Ranks). "Can't block" is the parser's own claim. The graveyard ability is
    `return_self_from_graveyard` with an ``extra_counters`` +1/+1; its discount is the cost's own
    ``dynamic_reduction`` gated by the new ``opponent_controls_at_least`` condition (some opponent with four or more
    nonbasic lands).
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {"keywords": ["cant_block"], "affects": "self"})]),
        AbilitySpec(
            "activated",
            [EffectSpec("return_self_from_graveyard", {"extra_counters": {"kind": "+1/+1", "count": 1}})],
            cost={"mana": "{4}{B}{B}", "dynamic_reduction": {
                "generic_per": 4,
                "active_if": {"kind": "opponent_controls_at_least", "min": 4,
                              "filter": {"card_type": "land", "nonbasic": True}},
            }},
        ),
    ]


register("Razorlash Transmogrant", _razorlash_transmogrant)
