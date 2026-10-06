from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _druid_of_purification() -> list[AbilitySpec]:
    """When this creature enters, starting with you, each player may choose an artifact or enchantment you don't control. Destroy each permanent chosen this way.

    — PLAY-ALL (Living Energy). `choose_player_objects` (Mardu Surge's APNAP chooser) with the new ``destroy_not_yours``
    action: every player picks one artifact or enchantment the Druid's controller doesn't control, then all picks are
    destroyed at once (RULE 608.2e).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_player_objects", {
                "action": "destroy_not_yours", "player_scope": "each_player", "optional": True,
                "card_types_any": ["artifact", "enchantment"],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Druid of Purification", _druid_of_purification)
