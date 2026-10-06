from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _collective_effort() -> list[AbilitySpec]:
    """Escalate—Tap an untapped creature you control. (Pay this cost for each mode chosen beyond the first.)
    Choose one or more —
    • Destroy target creature with power 4 or greater.
    • Destroy target enchantment.
    • Put a +1/+1 counter on each creature target player controls.

    — PLAY-ALL (Counter Blitz). A "choose one or more" modal block (``at_least``) whose Escalate cost is a creature tap rather than mana:
    ``escalate_tap_creature`` makes `GameEngine._escalate_tap_count` tap one untapped creature per mode beyond the first (`can_cast`
    requires them; **simplification:** the creatures are chosen automatically, lowest power first). Modes: `destroy` over a creature with
    ``min_power`` 4, `destroy` over an enchantment, and `add_counters` over the targeted player's creatures (``group_player``).
    """
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={"choose": 1, "at_least": True, "escalate_tap_creature": True, "options": [
                [EffectSpec("destroy", {"target_kind": "creature", "creature_filter": {"min_power": 4}})],
                [EffectSpec("destroy", {"target_kind": "enchantment"})],
                [EffectSpec("add_counters", {
                    "count": 1, "kind": "+1/+1", "group_player": "player",
                    "group": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
                })],
            ], "descriptions": [
                "Destroy target creature with power 4 or greater.",
                "Destroy target enchantment.",
                "Put a +1/+1 counter on each creature target player controls.",
            ]},
        ),
    ]


register("Collective Effort", _collective_effort)
