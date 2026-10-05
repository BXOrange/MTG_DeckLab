from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _explorers_scope() -> list[AbilitySpec]:
    """Whenever equipped creature attacks, look at the top card of your
    library. If it's a land card, you may put it onto the battlefield tapped.
    Equip {1}
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("peek_top_land_battlefield_tapped", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
        )
    ]


register("Explorer's Scope", _explorers_scope)
