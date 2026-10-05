from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _coat_of_arms() -> list[AbilitySpec]:
    """Each creature gets +1/+1 for each other creature on the battlefield
    that shares at least one creature type with it.

    — Coat of Arms. A layer-7d per-count anthem whose count is relative to
    each *affected* creature, not to the Coat: `continuous._pt_mod_count`
    already evaluates a structured selector whose filter carries
    ``shares_creature_type_with_reference`` against the recipient ("it"),
    and ``not_reference`` drops that recipient from its own count (the
    "other"). ``of: "any"`` counts every player's creatures, and
    `combat._creature_subtypes` already treats a changeling as sharing a
    type with every creature. The parser reaches the same selector for its
    "that shares a creature type with it" counts (PAR-123) but not for this
    all-creatures static, hence the hand-authored entry.
    """
    shared_type_count = {
        "zone": "battlefield", "of": "any",
        "filter": {"card_type": "creature", "shares_creature_type_with_reference": True,
                   "not_reference": True},
    }
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "all_creatures", "power": 1, "toughness": 1,
                "power_count": shared_type_count, "toughness_count": dict(shared_type_count),
            })],
        ),
    ]


register("Coat of Arms", _coat_of_arms)
