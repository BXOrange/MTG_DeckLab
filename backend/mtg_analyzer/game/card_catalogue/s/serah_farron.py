from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _serah_farron() -> list[AbilitySpec]:
    """The first legendary creature spell you cast each turn costs {2} less to
    cast.
    At the beginning of combat on your turn, if you control two or more other
    legendary creatures, you may transform Serah Farron.

    — PLAY-ALL Step 2 (SpongeBob). The transform trigger is the parser's own
    claim, reproduced. The discount is a `cost_reduction` for legendary
    creature spells (``spell_type: creature`` + the ``spell_legendary`` filter)
    gated by the new ``first_legendary_creature_spell_this_turn`` condition
    (`static_conditions`, fed by `turn_history.spell_type_cast_counts`'s new
    ``legendary_creature`` tally) — Acolyte of Bahamut's "first spell this
    turn" shape. This registers the front face only; the back face (Crystallized
    Serah) is not in the card cache, so it is not authored here.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "generic": 2, "spell_type": "creature", "spell_legendary": True,
                "active_if": {"kind": "first_legendary_creature_spell_this_turn"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "optional", {"effects": [{"type": "transform", "params": {}}]},
                condition={
                    "kind": "control_count",
                    "selector": {"zone": "battlefield", "of": "you", "filter": {
                        "legendary": True, "card_type": "creature", "not_reference": True,
                    }},
                    "min": 2,
                },
            )],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you",
            },
        ),
    ]


register("Serah Farron", _serah_farron)
