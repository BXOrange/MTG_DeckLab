from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rise_from_the_grave() -> list[AbilitySpec]:
    """Put target creature card from a graveyard onto the battlefield
    under your control. That creature is a black Zombie in addition to
    its other colors and types.

    — MEC-43 round 2. The type/colour addition is `grant_until`'s
    ``previous_subject``/``duration="rest_of_game"`` combination (RULE
    611.2c — a resolving spell's own effect with no stated duration lasts
    indefinitely), reading back the just-reanimated creature the same way
    "It fights…" reads a prior clause's target — RULE 400.7 keeps the
    object's `instance_id` (and so its place in `previous_targets`) stable
    across the graveyard-to-battlefield zone change.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "under_your_control": True,
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Zombie"]}},
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "color_change", "params": {"colors": ["B"], "set": False}},
                }),
            ],
        )
    ]


register("Rise from the Grave", _rise_from_the_grave)
