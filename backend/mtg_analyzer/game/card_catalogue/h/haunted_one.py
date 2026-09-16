from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _haunted_one() -> list[AbilitySpec]:
    """Commander creatures you own have "Whenever this creature becomes
    tapped, it and other creatures you control that share a creature type
    with it each get +2/+0 and gain undying until end of turn."

    — PAR-32 / MEC-59. Hand-authored: the granted trigger's own event
    (RULE 603.2 "becomes tapped", `EventType.TAPPED`) was already
    grantable-shaped (the same `instance_id`-keyed self-subject scoping
    every other RULE 603.1 object-subject grant uses), but the affected
    group — "it **and** other creatures you control that share a creature
    type with it" (RULE 205.3g, checked against the granting object's own
    *live* subtypes, not a fixed list) — had no selector. New `PumpEffect`
    selector `self_and_shared_creature_type_you_control` (`game/
    effects.py`): self plus every other creature the same controller
    controls whose printed subtypes overlap the source's own, computed at
    resolve time so it re-scopes correctly per affected commander creature
    under this same grant.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_triggered_ability", {
                    "affects": "commander_creatures_you_own",
                    "trigger_event": "TAPPED",
                    "grant_effects": [
                        {"type": "pump", "params": {
                            "power": 2, "toughness": 0,
                            "keywords": ["undying"],
                            "selector": "self_and_shared_creature_type_you_control",
                        }},
                    ],
                }),
            ],
        ),
    ]


register("Haunted One", _haunted_one)
