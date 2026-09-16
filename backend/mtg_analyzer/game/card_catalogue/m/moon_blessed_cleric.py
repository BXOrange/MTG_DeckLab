from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _moon_blessed_cleric() -> list[AbilitySpec]:
    """Moon-Blessed Cleric (Creature — Human Elf Cleric, {2}{W})

    "Divine Intervention — When this creature enters, you may search your
    library for an enchantment card, reveal it, then shuffle and put that
    card on top."

    A plain optional search onto the library's own top — the ability-word
    "Divine Intervention —" prefix carries no separate rules meaning
    (RULE 207.2c reminder-text-style flavour heading).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "enchantment"}, "destination": "library_top"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
        ),
    ]


register("Moon-Blessed Cleric", _moon_blessed_cleric)
