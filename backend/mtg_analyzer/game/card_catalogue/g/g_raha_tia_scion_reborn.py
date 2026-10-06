from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _g_raha_tia_scion_reborn() -> list[AbilitySpec]:
    """Lifelink
    Throw Wide the Gates — Whenever you cast a noncreature spell, you may pay X life, where X is that spell's mana value. If you do, create a 1/1 colorless Hero creature token and put X +1/+1 counters on it. Do this only once each turn.

    — PLAY-ALL (Scions & Spellcraft). Lifelink is the keyword's. The parser's 2-life shape (`pay_cost_then` + token +
    counters + `action_once_per_turn_marker`) with the new ``x_from_trigger_event``/``pay_life_x``: X is the cast spell's ``mana_value``,
    pricing the life payment and binding the counters' ``"$x"``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "", "pay_life_x": True, "x_from_trigger_event": "mana_value",
                "effects": [
                    {"type": "create_token", "params": {
                        "count": 1, "power": 1, "toughness": 1, "colors": [], "subtypes": ["Hero"], "keywords": [],
                        "token_name": "Hero",
                    }},
                    {"type": "add_counters", "params": {"count": "$x", "kind": "+1/+1", "previous_subject": True}},
                    {"type": "action_once_per_turn_marker", "params": {}},
                ],
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"without_card_type": "creature"}},
        ),
    ]


register("G'raha Tia, Scion Reborn", _g_raha_tia_scion_reborn)
