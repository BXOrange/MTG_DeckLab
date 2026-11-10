from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _khan_despot_by_design() -> list[AbilitySpec]:
    """Trample
    When Khan enters, he deals 1 damage to each opponent and each creature your opponents control.

    RULE 120.3: one damage event per recipient from a single source; the
    opponents-creature group and the opponents themselves are the
    ``group`` / ``group_and_players`` pair the parser emits for the
    reordered phrasing.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "group": {"zone": "battlefield", "of": "opponents", "filter": {"card_type": "creature"}},
                "group_and_players": "each_opponent", "amount": 1,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Khan, Despot by Design", _khan_despot_by_design)
