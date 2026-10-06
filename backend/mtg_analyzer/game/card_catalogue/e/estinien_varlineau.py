from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _estinien_varlineau() -> list[AbilitySpec]:
    """Whenever you cast a noncreature spell, put a +1/+1 counter on Estinien Varlineau. It gains flying until end of turn.
    At the beginning of your second main phase, you draw X cards and lose X life, where X is the number of your opponents who were dealt combat damage by Estinien Varlineau or a Dragon this turn.

    — PLAY-ALL (Scions & Spellcraft). The cast trigger is the parser's. The second-main trigger measures the new
    ``opponents_dealt_combat_damage_by_self_or_dragon_this_turn`` count selector (event-derived, dealers found in any zone).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}), EffectSpec("pump", {"keywords": ["flying"]})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"without_card_type": "creature"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": {"kind": "count_selector", "selector": "opponents_dealt_combat_damage_by_self_or_dragon_this_turn"}}),
                EffectSpec("lose_life", {"amount": {"kind": "count_selector", "selector": "opponents_dealt_combat_damage_by_self_or_dragon_this_turn"}}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main2"}, "phase_relation": "you"},
        ),
    ]


register("Estinien Varlineau", _estinien_varlineau)
