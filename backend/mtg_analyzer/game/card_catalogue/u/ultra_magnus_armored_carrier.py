from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Formidable (an ability word): "attacking creatures you control" total power at least this much.
FORMIDABLE_TOTAL_POWER = 8


def _ultra_magnus_armored_carrier() -> list[AbilitySpec]:
    """Living metal (During your turn, this Vehicle is also a creature.)
    Haste
    Formidable -- Whenever Ultra Magnus attacks, attacking creatures you control gain indestructible until end of
    turn. If those creatures have total power 8 or greater, convert Ultra Magnus.

    -- MEC-137. Back face of Ultra Magnus, Tactician. The pump is the parser's own shape; the conditional convert
    reads the existing ``total_power_attacking_creatures_you_control`` count at resolution (RULE 508.1).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("pump", {
                    "keywords": ["indestructible"],
                    "selector": {"zone": "battlefield", "of": "you", "filter": {"attacking": True, "card_type": "creature"}},
                }),
                EffectSpec("transform", {}, condition={
                    "kind": "control_count", "selector": "total_power_attacking_creatures_you_control",
                    "min": FORMIDABLE_TOTAL_POWER,
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="whenever ~ attacks, attacking creatures you control gain indestructible until end of turn. "
                     "if those creatures have total power 8 or greater, convert ~.",
        ),
    ]


register("Ultra Magnus, Armored Carrier", _ultra_magnus_armored_carrier)
