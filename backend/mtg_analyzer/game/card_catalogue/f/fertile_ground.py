from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fertile_ground() -> list[AbilitySpec]:
    """Enchant land
    Whenever enchanted land is tapped for mana, its controller adds an
    additional one mana of any color.

    The attached-land trigger is Wild Growth's existing triggered-mana
    ability.  ``ANY`` preserves the controller's colour choice and
    ``event_controller`` correctly follows the enchanted land if control
    changes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["ANY"], "recipient": "event_controller"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
        )
    ]


register("Fertile Ground", _fertile_ground)
