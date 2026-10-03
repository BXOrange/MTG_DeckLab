from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _roaring_earth() -> list[AbilitySpec]:
    """Landfall — Whenever a land you control enters, put a +1/+1 counter on
    target creature or Vehicle you control.
    Channel — {X}{G}{G}, Discard this card: Put X +1/+1 counters on target land
    you control. It becomes a 0/0 green Spirit creature with haste. It's still
    a land.

    — PLAY-ALL Step 2 (Kodama). The landfall head is the parser's own (group
    ``type: land``, ``controller: you``) with the new target kind
    `creature_or_vehicle_you_control`. Channel is a hand-zone activation
    (``discard_self``, Sokenzan's shape) chaining `add_counters` (X counters on
    the chosen land) and Kamahl's two `grant_until` statics on that same land
    (`previous_subject`): a layer-4 `type_change` (creature + Spirit, 0/0 —
    ``add_types`` only *adds*, so it is still a land) and haste. The duration is
    ``rest_of_game`` because the printed text has none — the animation is
    permanent. The layer-5 color grant makes the animated land green.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "target_kind": "creature_or_vehicle_you_control"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"count": "x", "kind": "+1/+1", "target_kind": "land_you_control"}),
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "add_subtypes": ["Spirit"], "power": 0, "toughness": 0,
                    }},
                    "duration": "rest_of_game", "target_kind": None, "previous_subject": True,
                    "extra_statics": [
                        {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
                        {"type": "color", "params": {"colors": ["G"], "set": True}},
                    ],
                }),
            ],
            cost={"mana": "{X}{G}{G}", "discard_self": True},
        ),
    ]


register("Roaring Earth", _roaring_earth)
