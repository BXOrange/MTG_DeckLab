from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pathbreaker_ibex() -> list[AbilitySpec]:
    """Whenever this creature attacks, creatures you control gain trample and
    get +X/+X until end of turn, where X is the greatest power among
    creatures you control.

    — PLAY-ALL Step 2 (Kodama). Blossoming Bogbeast's group `pump`
    (``selector="creatures_you_control"``, ``keywords=["trample"]``,
    ``amount_from_count_selector``) on an attack trigger, with the
    `count_selector` ``greatest_power_among_creatures_you_control`` (PAR-80's
    "greatest `<metric>` among `<scope>` you control" reader) as X.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "selector": "creatures_you_control", "keywords": ["trample"],
                "amount_from_count_selector": "greatest_power_among_creatures_you_control",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Pathbreaker Ibex", _pathbreaker_ibex)
