from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _massacre_girl_known_killer() -> list[AbilitySpec]:
    """Menace
    Creatures you control have wither. (They deal damage to creatures in
    the form of -1/-1 counters.)
    Whenever a creature an opponent controls dies, if its toughness was
    less than 1, draw a card.

    Menace folds in from the RULE 702 catalogue. Authored: the wither
    anthem (ordinary layer-6 ``grant_keyword``), and the dies trigger —
    the C3a "an opponent controls" group subject with a new
    `ConditionalEffect` ``dying_creature_toughness_below`` gate on the DIES
    event's snapshotted last-known toughness (RULE 603.6a).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "keywords": ["wither"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature",
                              "controller": "not_you", "other": False},
                # RULE 603.4 intervening-if on the dying creature's own
                # last-known toughness (checked at trigger time).
                "dying_toughness_below": 1,
            },
        ),
    ]


register("Massacre Girl, Known Killer", _massacre_girl_known_killer)
