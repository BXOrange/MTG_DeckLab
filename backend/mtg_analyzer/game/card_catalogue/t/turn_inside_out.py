from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _turn_inside_out() -> list[AbilitySpec]:
    """Target creature gets +3/+0 until end of turn. When it dies this turn,
    manifest dread.

    — PLAY-ALL Step 2 (Wick Snail Boom). The PAR-102 shape for "target
    creature gets +X/+0 until end of turn. When that creature dies this turn,
    `<effect>`": a `pump` on the target, then `create_turn_trigger` over
    ``previous_subject`` (the trigger watches the creature the pump chose, no
    second target) whose DIES body is `manifest_dread` (the controller of the
    spell manifests — the trigger is bound to the spell, so "you" is its
    caster).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("pump", {"power": 3, "toughness": 0, "target_kind": "creature"}),
                EffectSpec("create_turn_trigger", {
                    "trigger": {"event": "DIES", "condition": {"subject": "self"}},
                    "effects": [{"type": "manifest_dread", "params": {}}],
                    "optional": False, "previous_subject": True,
                    "description": "when it dies this turn, manifest dread.",
                }),
            ],
        )
    ]


register("Turn Inside Out", _turn_inside_out)
