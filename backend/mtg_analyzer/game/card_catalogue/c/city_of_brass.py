from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _city_of_brass() -> list[AbilitySpec]:
    """Whenever this land becomes tapped, it deals 1 damage to you.
    {T}: Add one mana of any color.

    The mana ability itself is covered by the engine's plain mana model
    (`mana_abilities_for`, no spec needed) — only the "becomes tapped"
    drawback needs a spec, `EventType.TAPPED` (already fired for every
    genuine untapped→tapped transition, not just a mana tap).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"selector": "controller"})],
            trigger={"event": EventType.TAPPED, "condition": {"subject": "self"}},
        )
    ]


register("City of Brass", _city_of_brass)
