from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _michelangelo_the_heart() -> list[AbilitySpec]:
    """Raid is checked at the second main phase and again on resolution (RULE 603.4)."""
    return [AbilitySpec("triggered", [
        EffectSpec("add_counters", {"count": 1, "target_kind": "creature_including_self"}),
        EffectSpec("create_token", {"token_name": "Food", "count": 1}),
    ], trigger={"event": "STEP_BEGIN", "filter": {"step": "main2"}, "phase_relation": "you",
                "active_if": {"kind": "you_attacked_this_turn"}})]


register('Michelangelo, the Heart', _michelangelo_the_heart)
