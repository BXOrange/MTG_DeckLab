from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _venerable_warsinger() -> list[AbilitySpec]:
    """Vigilance, trample
    Whenever this creature deals combat damage to a player, you may return
    target creature card with mana value X or less from your graveyard to the
    battlefield, where X is the amount of damage this creature dealt to that
    player."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield",
                "max_mana_value": "trigger_damage_amount", "optional": True,
            })],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                     "filter": {"is_player": True, "combat": True}},
        ),
    ]


register("Venerable Warsinger", _venerable_warsinger)
