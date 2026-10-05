from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _progenitor_exarch() -> list[AbilitySpec]:
    """When this creature enters, incubate 3 X times.
    {T}: Transform target Incubator token you control.

    — "incubate 3 **X times**": the repeat count is the creature's own
    announced {X} ({X}{X} in its cost), `GameObject.x_paid` (RULE 107.3c,
    stamped at cast time and still present when the ETB trigger resolves —
    the same field enters-with-X-counters reads). New
    `continuous.count_selector` key ``"source_x_paid"``, consumed by
    `create_token`'s existing ``count_selector`` path.

    The "{T}: Transform target Incubator token you control" ability reuses
    the `Incubator` token's own transform shape exactly (`grant_until` /
    ``type_change`` / ``rest_of_game`` — a genuinely permanent RULE 712.8
    animation into a 0/0 Phyrexian artifact creature, its +1/+1 counters
    doing the rest), just with a RULE 115 target instead of self: the new
    ``incubator_token_you_control`` target kind (a token named "Incubator"
    this ability's controller controls).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Incubator",
                "count_selector": "source_x_paid",
                "extra_counters": {"kind": "+1/+1", "count": 3},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game",
                "target_kind": "incubator_token_you_control",
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"], "add_subtypes": ["Phyrexian"],
                        "power": 0, "toughness": 0,
                    },
                },
            })],
            cost={"text": "{T}"},
        ),
    ]


register("Progenitor Exarch", _progenitor_exarch)
