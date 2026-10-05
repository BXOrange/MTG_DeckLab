from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _braids_arisen_nightmare() -> list[AbilitySpec]:
    """Optional sacrifice followed by each opponent's matching-type choice.

    Capture the sacrificed permanent's last-known types once; the opponent
    choices must retain that snapshot even if Braids itself was sacrificed.
    """
    return [AbilitySpec("triggered", [EffectSpec("choose_objects", {
        "action": "sacrifice", "optional": True,
        "card_types_any": ["artifact", "creature", "enchantment", "land", "planeswalker"],
        "then": [{"type": "choose_player_objects", "params": {
                "action": "sacrifice", "optional": True, "player_scope": "each_opponent",
                "card_types_any": {"kind": "sacrificed_card_types"},
                "else_effects": [
                    {"type": "lose_life", "params": {"amount": 2, "player_id": {"kind": "choosing_player_id"}}},
                    {"type": "draw", "params": {"count": 1}},
                ],
        }}],
    })], trigger={"event": "STEP_BEGIN", "filter": {"step": "end"}, "phase_relation": "you"})]


register("Braids, Arisen Nightmare", _braids_arisen_nightmare)
