from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-43 round 4B: cEDH staples 2 / K'rrik cEDH trigger-composition cluster
# (ETB / cast / upkeep triggers) — 7 of 8 cards, new primitives: `RulesEngine.
# _collect_self_cast_triggers` (RULE 601.2i "when you cast this spell"),
# `continuous.hand_size_modifier_for`, `ChooseObjectsEffect.player_selector`,
# `ConniveEffect` (RULE 701.47), and `effect_binder`'s new
# `spell_characteristic_equals_chosen_number` trigger predicate. Kozilek's
# own third clause is left a documented gap — see its own docstring.
# ---------------------------------------------------------------------------


def _bontus_monument() -> list[AbilitySpec]:
    """Black creature spells you cast cost {1} less to cast.
    Whenever you cast a creature spell, each opponent loses 1 life and you
    gain 1 life.

    — MEC-43 round 4B. The cast trigger already parses on its own —
    reproduced verbatim. The cost reduction is `cost_reduction`'s existing
    `spell_type`/`spell_color` combination — Ruby Medallion's own
    `spell_color` filter plus the ordinary `spell_type="creature"` one,
    which already compose via plain AND in `continuous.cost_reduction_for`
    but had never been exercised together by a real card before this one.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"}),
                EffectSpec("gain_life", {"amount": 1}),
            ],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "you"},
                "spell_card_types": ["creature"],
            },
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "spell_type": "creature", "spell_color": "B"})],
        ),
    ]


register("Bontu's Monument", _bontus_monument)
