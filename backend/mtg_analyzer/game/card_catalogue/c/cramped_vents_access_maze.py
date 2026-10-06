from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cramped_vents_access_maze() -> list[AbilitySpec]:
    """When you unlock this door, this Room deals 6 damage to target creature an opponent controls. You gain life equal to the excess damage dealt this way.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — PLAY-ALL (Miracle Worker). A `bind` over `damage` + `gain_life`: the excess is measured before the damage, as 6 minus the
    target's toughness when positive. **Simplification:** damage already marked on the creature is not subtracted from its remaining
    lethal damage. **Simplification (as in Experimental Lab // Staff Room):** Rooms have no door state in the engine, so casting the Room is its
    door unlocking — the ability is an enters trigger — and the cache holds only this front door's text.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "excess",
                "amount": {
                    "kind": "if",
                    "condition": {
                        "kind": "amount_compare", "op": "gt",
                        "left": {"kind": "fixed", "amount": 6},
                        "right": {"kind": "characteristic", "characteristic": "toughness", "of": "target"},
                    },
                    "then": {
                        "kind": "abs_diff",
                        "left": {"kind": "fixed", "amount": 6},
                        "right": {"kind": "characteristic", "characteristic": "toughness", "of": "target"},
                    },
                    "otherwise": {"kind": "fixed", "amount": 0},
                },
                "effects": [
                    {"type": "damage", "params": {"amount": 6, "target_kind": "creature_you_dont_control"}},
                    {"type": "gain_life", "params": {"amount": "$excess"}},
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Cramped Vents // Access Maze", _cramped_vents_access_maze)
register("Cramped Vents", _cramped_vents_access_maze)
