from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ghostly_flicker() -> list[AbilitySpec]:
    """Exile two target artifacts, creatures, and/or lands you control, then
    return those cards to the battlefield under your control.

    — PLAY-ALL Step 2 (Wick Snail Boom). Cloudshift's `blink`
    (``under_your_control``) with ``target_count: 2`` over the new
    ``artifact_creature_or_land_you_control`` target frame
    (`targeting.TARGET_FRAMES`: whitelist, German label, a three-type
    predicate). The two targets are distinct, as RULE 115.3 requires of two
    "target" words in one instruction.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("blink", {
                "target_kind": "artifact_creature_or_land_you_control",
                "under_your_control": True, "target_count": 2,
            })],
        )
    ]


register("Ghostly Flicker", _ghostly_flicker)
