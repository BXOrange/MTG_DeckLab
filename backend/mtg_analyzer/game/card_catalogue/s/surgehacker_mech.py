from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _surgehacker_mech() -> list[AbilitySpec]:
    """Menace
    When this Vehicle enters, it deals damage equal to twice the number of Vehicles you control to target creature or planeswalker an opponent controls.
    Crew 4

    — PLAY-ALL (Shorikai Vehicles). Menace and Crew are keywords. A `bind` measuring the Vehicles you control (``multiply: 2``) into one `damage`
    to a creature or planeswalker an opponent controls — the count includes the Mech itself, which is already on the battlefield.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "count_selector", "multiply": 2, "selector": {
                    "zone": "battlefield", "of": "you", "filter": {"subtype": "vehicle"}}},
                "effects": [{"type": "damage", "params": {"amount": "$n", "target_kind": "creature_or_planeswalker_you_dont_control"}}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Surgehacker Mech", _surgehacker_mech)
