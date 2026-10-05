from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nissa_vital_force() -> list[AbilitySpec]:
    """+1: Untap target land you control. Until your next turn, it becomes a
    5/5 Elemental creature with haste. It's still a land.
    −3: Return target permanent card from your graveyard to your hand.
    −6: You get an emblem with "Whenever a land you control enters, you may
    draw a card."

    — PLAY-ALL Step 2 (Kodama). The −3 and the −6 are the parser's own
    claims, reproduced (the emblem's inner ability is the serialized spec the
    parser emits). The +1 is two clauses on one target: `tap` ``untap`` on a
    ``land_you_control``, then `grant_until` over ``previous_subject`` ("it")
    with the ``your_next_turn`` duration (RULE 611.2b) — a layer-4
    `type_change` (creature, Elemental, 5/5; the land type stays, "it's still
    a land") plus a haste keyword grant, the same two-static shape the
    parser uses for "target land becomes a 4/4 Elemental creature with haste".
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("tap", {"target_kind": "land_you_control", "untap": True}),
                EffectSpec("grant_until", {
                    "duration": "your_next_turn", "previous_subject": True,
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "power": 5, "toughness": 5, "add_subtypes": ["Elemental"],
                    }},
                    "extra_statics": [{"type": "grant_keyword", "params": {"keywords": ["haste"]}}],
                }),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_permanent", "destination": "hand"})],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": {
                "ability_kind": "triggered",
                "effects": [{"type": "draw", "params": {"count": 1}}],
                "trigger": {
                    "event": "ENTERS_BATTLEFIELD",
                    "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
                },
                "cost": None, "target": None, "keyword": None, "modes": None, "additional_cost": None,
                "additional_cost_optional": False, "conditional_flash": None, "cast_timing_restriction": None,
                "cast_condition": None, "flash_extra_cost": None, "free_cast_condition": None,
                "optional": True,
                "raw_text": "whenever a land you control enters, you may draw a card.",
                "parser": {"version": "nested", "source": "rule:oracle", "confidence": 1.0},
            }})],
            cost={"loyalty": -6},
        ),
    ]


register("Nissa, Vital Force", _nissa_vital_force)
