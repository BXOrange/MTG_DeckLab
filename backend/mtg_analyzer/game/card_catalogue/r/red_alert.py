from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Red Alert!'s printed self-discount ({2}).
RED_ALERT_DISCOUNT = 2


def _red_alert() -> list[AbilitySpec]:
    """This spell costs {2} less to cast if a creature is attacking you.
    Creatures you control get +2/+0 until end of turn.

    RULE 601.2f: the self cost reduction is gated on the number of
    creatures whose declared defender is this player
    (``creatures_attacking_you``, RULE 506.2).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": RED_ALERT_DISCOUNT,
                "active_if": {"kind": "control_count", "selector": "creatures_attacking_you", "min": 1},
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("pump", {
                "power": 2, "toughness": 0,
                "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
            })],
        ),
    ]


register("Red Alert!", _red_alert)
