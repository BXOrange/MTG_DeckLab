from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_breach() -> list[AbilitySpec]:
    """Whenever a player casts a spell, that player returns a land they
    control to its owner's hand.

    — MEC-43. A plain "group" subject with no ``controller`` filter (any
    player's cast, the same idiom Nether Void's own unscoped trigger
    uses); the new `BounceOwnLandFromTriggerEffect` reads the firing
    `SPELL_CAST` event's own ``player_id`` as the chooser/owner instead of
    this ability's own controller.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bounce_own_land_from_trigger", {})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}},
        ),
    ]


register("Mana Breach", _mana_breach)
