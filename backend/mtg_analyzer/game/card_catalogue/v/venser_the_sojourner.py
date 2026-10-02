from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _venser_the_sojourner() -> list[AbilitySpec]:
    """+2: Exile target permanent you own. Return it to the battlefield under
    your control at the beginning of the next end step.
    −1: Creatures can't be blocked this turn.
    −8: You get an emblem with "Whenever you cast a spell, exile target
    permanent."

    — PLAY-ALL Step 2 (SpongeBob). The −1 and the −8 are the parser's own
    claims, reproduced (the emblem's inner ability is the serialized spec the
    parser emits). The +2 is Teferi's Time Twist's delayed-return flicker
    (`exile` with ``track_exiled_with`` + an any-end-step `create_delayed_
    trigger` running `return_all_exiled_with`) over the new owner-scoped
    ``permanent_you_own`` target frame (`targeting.TARGET_FRAMES`). It returns
    under its owner's control, which is "your control" because you own it.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "permanent_you_own", "track_exiled_with": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any",
                    "effects": [{"type": "return_all_exiled_with", "params": {}}],
                    "description": "Bringe diese Karte am Anfang des nächsten Endsegments ins Spiel zurück.",
                }),
            ],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("unblockable", {"selector": "all_creatures"})],
            cost={"loyalty": -1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": {
                "ability_kind": "triggered",
                "effects": [{"type": "exile", "params": {"target_kind": "permanent"}}],
                "trigger": {"event": "SPELL_CAST", "condition": {"subject": "you"}},
                "cost": None, "target": None, "keyword": None, "modes": None, "additional_cost": None,
                "additional_cost_optional": False, "conditional_flash": None, "cast_timing_restriction": None,
                "cast_condition": None, "flash_extra_cost": None, "free_cast_condition": None,
                "optional": False,
                "raw_text": "whenever you cast a spell, exile target permanent.",
                "parser": {"version": "nested", "source": "rule:oracle", "confidence": 1.0},
            }})],
            cost={"loyalty": -8},
        ),
    ]


register("Venser, the Sojourner", _venser_the_sojourner)
