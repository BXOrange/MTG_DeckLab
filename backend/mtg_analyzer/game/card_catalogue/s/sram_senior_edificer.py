from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sram_senior_edificer() -> list[AbilitySpec]:
    """Whenever you cast an Aura, Equipment, or Vehicle spell, draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "group", "controller": "you"},
                "spell_subtype_any": ["Aura", "Equipment", "Vehicle"],
            },
        )
    ]


register("Sram, Senior Edificer", _sram_senior_edificer)
