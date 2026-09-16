from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _malcolm_keen_eyed_navigator() -> list[AbilitySpec]:
    """Flying
    Whenever one or more Pirates you control deal damage to your
    opponents, you create a Treasure token for each opponent dealt
    damage. (It's an artifact with "{T}, Sacrifice this token: Add one
    mana of any color.")
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH M-K). **Documented simplification**: scoped to *combat*
    damage (the new ``contributor_subtype`` trigger key on the existing
    MEC-29 aggregate event, `GameEngine._apply_combat_damage`'s own
    ``subtypes`` field — the union of every contributing creature's
    subtypes that step), not the printed card's fully general "deal
    damage" — noncombat damage from a controlled Pirate is a vanishingly
    rare case this template doesn't reach. "A Treasure for each opponent
    dealt damage" needs no explicit count: the aggregate event already
    fires once per (controller, opponent-hit) pair (MEC-29), so each
    firing is already scoped to exactly one opponent. Flying/Partner are
    printed keywords, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "group", "controller": "you"},
                "contributor_subtype": "pirate",
            },
        ),
    ]


register("Malcolm, Keen-Eyed Navigator", _malcolm_keen_eyed_navigator)
