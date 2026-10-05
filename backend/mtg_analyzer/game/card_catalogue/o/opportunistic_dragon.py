from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _opportunistic_dragon() -> list[AbilitySpec]:
    """Flying
    When this creature enters, choose target Human or artifact an opponent controls. For as long as this creature remains on the battlefield, gain control of that permanent, it loses all abilities, and it can't attack or block.

    — PLAY-ALL Step 2 (Temur Roar). Pyreswipe Hawk's `grant_until` — the layer-2 ``control_change`` bounded by
    ``source_on_battlefield`` — with the other two clauses as ``extra_statics`` on the same target and the
    same lifetime: `remove_all_abilities` and the `cant_attack`/`cant_block` flag keywords. The statics are
    applied in timestamp order within layer 6, so the flags are listed after the ability removal and survive
    it. The target is the new ``human_or_artifact_you_dont_control`` kind. Flying is a printed keyword.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "static": {"type": "control_change", "params": {}},
                "target_kind": "human_or_artifact_you_dont_control",
                "condition": {"kind": "source_on_battlefield"},
                "extra_statics": [
                    {"type": "remove_all_abilities", "params": {}},
                    {"type": "grant_keyword", "params": {"keywords": ["cant_attack", "cant_block"]}},
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Opportunistic Dragon", _opportunistic_dragon)
