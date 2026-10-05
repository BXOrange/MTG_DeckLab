from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from .deepglow_skate import ANY_NUMBER_TARGET_CAP


def _depthshaker_titan() -> list[AbilitySpec]:
    """When this creature enters, any number of target noncreature artifacts you
    control become 3/3 artifact creatures. Sacrifice them at the beginning of
    the next end step.
    Each artifact creature you control has melee, trample, and haste. (Whenever a
    creature with melee attacks, it gets +1/+1 until end of turn for each
    opponent you attacked this combat.)

    — PLAY-ALL Step 2 (Counter Intelligence). The ETB chains three existing
    pieces on the same chosen targets: `grant_until` ``type_change`` (Kamahl's
    animate, here with ``target_count`` via the any-number idiom of Deepglow
    Skate), then `previous_subject` for the delayed `sacrifice_specific`
    (`create_delayed_trigger` capturing ``previous_targets`` — Determined
    Iteration's shape). The lord grants trample and haste to every artifact
    creature you control, itself included.
    **Documented simplification: melee is not granted.** RULE 702.121 melee has
    no engine support at all (no keyword trigger, no "opponents attacked this
    combat" count) and a *granted* one would also need a granted-keyword trigger
    path like undying's; that is a keyword mechanic of its own, not a card file.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature", "artifact"], "power": 3, "toughness": 3,
                    }},
                    "duration": "end_of_turn", "target_kind": "noncreature_artifact_you_control",
                    "count": ANY_NUMBER_TARGET_CAP, "optional": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "previous_targets",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "card_type": "artifact", "keywords": ["trample", "haste"],
            })],
        ),
    ]


register("Depthshaker Titan", _depthshaker_titan)
