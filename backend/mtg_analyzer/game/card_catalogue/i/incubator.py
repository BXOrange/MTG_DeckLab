from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _incubator_token() -> list[AbilitySpec]:
    """{2}: Transform this token. It transforms into a 0/0 Phyrexian
    artifact creature.

    — the Incubate token family (RULE 701.51-adjacent): any Incubate
    producer's `create_token` call names this token "Incubator", and
    `bind_from_catalogue` binds a fresh token's abilities off its own
    name exactly like a real permanent, so this one registration covers
    every one of them. A genuinely permanent (RAW: no "until")
    characteristic change, so `grant_until` at ``duration="rest_of_game"``
    — targeting the token's own source, no RULE 115 target ("this
    token", the same self-acting mode `RegenerateEffect` uses) — animates
    it into a creature via `type_change`'s existing power/toughness
    animation params (0/0 base; its already-present +1/+1 counters do
    the rest) rather than a new primitive.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game", "target_kind": None,
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"], "add_subtypes": ["Phyrexian"],
                        "power": 0, "toughness": 0,
                    },
                },
            })],
            cost={"text": "{2}"},
        ),
    ]


register("Incubator", _incubator_token)
