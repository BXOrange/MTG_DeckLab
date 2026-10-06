from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _krile_baldesion() -> list[AbilitySpec]:
    """Lifelink
    Trace Aether — Whenever you cast a noncreature spell, you may return target creature card with mana value equal to that spell's mana value from your graveyard to your hand. Do this only once each turn.

    — PLAY-ALL (Scions & Spellcraft). Lifelink is the keyword's. The parser's `return_from_graveyard` with the target's
    ``exact_mana_value`` read off the cast spell (``trigger_spell_mana_value``), an optional trigger and the action-once-per-turn marker.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "destination": "hand",
                    "exact_mana_value": "trigger_spell_mana_value",
                }),
                EffectSpec("action_once_per_turn_marker", {}),
            ],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"without_card_type": "creature"}},
            optional=True,
        ),
    ]


register("Krile Baldesion", _krile_baldesion)
