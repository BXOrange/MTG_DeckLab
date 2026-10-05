from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bellowing_mauler() -> list[AbilitySpec]:
    """Each player chooses a nontoken creature or loses four life."""
    return [AbilitySpec("triggered", [EffectSpec("choose_player_objects", {
        "action": "sacrifice", "optional": True, "player_scope": "each_player",
        "permanent_filter": {"creature": True, "nontoken": True},
        "else_simultaneous": True,
        "else_effects": [{"type": "lose_life", "params": {
            "amount": 4, "player_id": {"kind": "choosing_player_id"},
        }}],
    })], trigger={"event": "STEP_BEGIN", "filter": {"step": "end"}, "phase_relation": "you"})]


register("Bellowing Mauler", _bellowing_mauler)
