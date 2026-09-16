from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _utopia_sprawl() -> list[AbilitySpec]:
    """Enchant Forest
    As this Aura enters, choose a color.
    Whenever enchanted Forest is tapped for mana, its controller adds an
    additional one mana of the chosen color.

    — Utopia Sprawl. Wild Growth's own triggered-mana-ability shape
    (RULE 605.1b/605.4 — resolves off-stack so the extra mana is there in
    time to spend), just reading `AddManaEffect`'s new `color_from_source_
    chosen_color` flag instead of a fixed `colors` list.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "color_from_source_chosen_color": True, "recipient": "event_controller",
            })],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
        ),
    ]


register("Utopia Sprawl", _utopia_sprawl)
