from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _barret_wallace() -> list[AbilitySpec]:
    """Reach
    Whenever Barret Wallace attacks, it deals damage equal to the number of equipped creatures you control to defending player.

    — PLAY-ALL (Limit Break). Reach is the keyword. An attack trigger over a `bind` of the new ``equipped_creatures_you_control`` count selector into `damage` aimed at the defending player.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n", "amount": {"kind": "count_selector", "selector": "equipped_creatures_you_control"},
                "effects": [{"type": "damage", "params": {"amount": "$n", "selector": "defending_player"}}],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Barret Wallace", _barret_wallace)
