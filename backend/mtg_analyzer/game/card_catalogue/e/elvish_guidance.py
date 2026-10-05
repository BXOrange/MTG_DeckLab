from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elvish_guidance() -> list[AbilitySpec]:
    """Enchant land
    Whenever enchanted land is tapped for mana, its controller adds an
    additional {G} for each Elf on the battlefield.

    — Eliferate deck batch. `Wild Growth`'s own triggered-mana-ability
    shape (RULE 605.1b/605.4), just with a board-scaled amount instead of a
    flat one: `AddManaEffect.amount_selector`'s new unscoped
    `creatures_of_type_<x>` count (`continuous.count_selector`) rather
    than the `_you_control`-scoped form every existing consumer used —
    "on the battlefield" here means every Elf, regardless of controller.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "color": "G", "amount_selector": "creatures_of_type_elf",
                "recipient": "event_controller",
            })],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
        ),
    ]


register("Elvish Guidance", _elvish_guidance)
