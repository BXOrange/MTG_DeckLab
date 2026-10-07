from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _secret_arcade_dusty_parlor() -> list[AbilitySpec]:
    """Nonland permanents you control and permanent spells you control are enchantments in addition to their other types.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — PLAY-ALL (Miracle Worker). A `type_change` adding ``enchantment`` to ``nonland_permanents_you_control``. **Simplification:** only
    the permanents on the battlefield are enchantments — a permanent spell on the stack is not. The left door's text (`game/rooms.py`, MEC-111).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {"affects": "nonland_permanents_you_control", "add_types": ["enchantment"]})],
        ),
    ]


register("Secret Arcade", _secret_arcade_dusty_parlor)
