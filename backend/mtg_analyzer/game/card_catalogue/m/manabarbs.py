from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-12: Ojer cEDH — new core primitive (`EventType.ACTIVATED_ABILITY`,
# RULE 602.2) + oracle-text-blind reuse of the existing TAPPED_FOR_MANA
# "group"/"nonbasic" scoping (binding/core.py) for the "punisher" family.
# ---------------------------------------------------------------------------


def _manabarbs() -> list[AbilitySpec]:
    """Whenever a player taps a land for mana, this enchantment deals 1
    damage to that player. — Manabarbs. The bare, untyped sibling of Price
    of Glory's own `TAPPED_FOR_MANA` consumer: no `"nonbasic"` filter, and
    `DealDamageEffect`'s existing `selector="event_player"` (Spellshock's
    shape) for "that player" instead of Price of Glory's reflexive-target
    destroy.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land"},
            },
        )
    ]


register("Manabarbs", _manabarbs)
