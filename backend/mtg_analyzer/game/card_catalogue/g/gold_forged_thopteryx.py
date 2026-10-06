from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gold_forged_thopteryx() -> list[AbilitySpec]:
    """Flying, lifelink
    Each legendary permanent you control has ward {2}.

    — PLAY-ALL (Hope to the last). Keywords are the catalogue's. The grant is `grant_keyword` ``ward_cost`` over the new
    ``legendary_permanents_you_control`` selector (the non-creature sibling of ``legendary_creatures_you_control``).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "legendary_permanents_you_control", "ward_cost": "{2}"})],
        ),
    ]


register("Gold-Forged Thopteryx", _gold_forged_thopteryx)
