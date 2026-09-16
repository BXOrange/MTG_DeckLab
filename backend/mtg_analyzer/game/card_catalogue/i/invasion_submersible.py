from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_submersible() -> list[AbilitySpec]:
    """When this Vehicle enters, return up to one other target nonland
    permanent to its owner's hand.
    Exhaust — Waterbend {3}: This Vehicle becomes an artifact creature. Put
    three +1/+1 counters on it. (Activate each exhaust ability only once.)

    — the ETB parses on its own (v215 "up to one other target nonland
    permanent"), reproduced here since a catalogue entry replaces the
    parser fallback. The Exhaust body is hand-authored: "becomes an
    artifact creature" is a `grant_until` rest-of-game `type_change`
    (0/0 base — this Vehicle's printed crew P/T — plus the three counters
    = a 3/3), and RULE 702.177a's once-per-game restriction is the
    `activate_only_once_marker` the binder folds into ``once_per_game``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {
                "target_kind": "nonland_permanent", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "target_kind": None,
                    "static": {"type": "type_change", "params": {
                        "add_types": ["artifact", "creature"], "power": 0, "toughness": 0,
                    }},
                }),
                EffectSpec("add_counters", {"kind": "+1/+1", "amount": 3, "target_kind": None}),
                EffectSpec("activate_only_once_marker", {}),
            ],
            cost={"mana": "{3}"},
        ),
    ]


register("Invasion Submersible", _invasion_submersible)
