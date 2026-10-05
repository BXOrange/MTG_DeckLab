from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _teferis_time_twist() -> list[AbilitySpec]:
    """Exile target permanent you control. Return that card to the battlefield
    under its owner's control at the beginning of the next end step. If it
    enters as a creature, it enters with an additional +1/+1 counter on it.

    — PLAY-ALL Step 2 (Wick Snail Boom). Waterbender's Restoration's
    delayed-return flicker: `exile` (``track_exiled_with``) on a
    ``permanent_you_control`` target, then a RULE 603.7 `create_delayed_trigger`
    at the next end step (``scope: any`` — "the next end step", whoever's)
    running `return_all_exiled_with`, here with its new
    ``counter_if_creature`` for the +1/+1 counter.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {"target_kind": "permanent_you_control", "track_exiled_with": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any",
                    "effects": [{"type": "return_all_exiled_with", "params": {
                        "counter_if_creature": {"kind": "+1/+1", "count": 1},
                    }}],
                    "description": "Bringe diese Karte am Anfang des nächsten Endsegments ins Spiel zurück.",
                }),
            ],
        )
    ]


register("Teferi's Time Twist", _teferis_time_twist)
