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

    Combat uses the existing contributor event (one per opponent hit).
    Noncombat uses a DAMAGE batch, counting distinct opponents hit by own
    Pirates during one simultaneous damage instruction.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                # PAR-131: the composed batch head's shape, recipient-scoped to
                # "your opponents".
                "condition": {"subject": "group", "controller": "you", "other": False,
                              "filter": {"subtype": "pirate"}, "recipient_is_opponent": True},
                "contributors": {"min": 1},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count_from_trigger_event": "matching_opponents"})],
            trigger={
                "event": "EVENT_BATCH",
                "batch": {"of": "DAMAGE", "min": 1},
                "condition": {"subject": "group", "controller": "you", "other": False,
                              "filter": {"subtype": "pirate"}, "recipient_is_opponent": True},
                "filter": {"combat": False, "is_player": True},
            },
        ),
    ]


register("Malcolm, Keen-Eyed Navigator", _malcolm_keen_eyed_navigator)
