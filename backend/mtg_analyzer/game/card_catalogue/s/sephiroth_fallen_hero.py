from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sephiroth_fallen_hero() -> list[AbilitySpec]:
    """Jenova Cells — Whenever Sephiroth attacks, you may put a cell counter on target creature. Until end of turn, each modified creature you control has base power and toughness 7/5. (Equipment, Auras you control, and counters are modifications.)
    The Reunion — {3}, Sacrifice a modified creature: Return this card from your graveyard to the battlefield tapped.

    — PLAY-ALL (Limit Break). The attack trigger is an optional cell `add_counters` on a target creature, then a `grant_until` ``pt_set`` 7/5 to the creatures you control that are modified (the ``modified``
    object filter, RULE 700.9), the group locked as the effect resolves (``lock_group``, RULE 611.2c). The Reunion is `return_self_from_graveyard` (tapped) behind a ``Sacrifice a modified creature`` cost.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "cell", "target_kind": "creature", "optional": True}),
                EffectSpec("grant_until", {
                    "static": {"type": "pt_set", "params": {
                        "affects": "creatures_you_control", "power": 7, "toughness": 5, "object_filter": {"modified": True},
                    }},
                    "duration": "end_of_turn", "target_kind": None, "lock_group": True,
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_self_from_graveyard", {"tapped": True})],
            cost={"text": "{3}, Sacrifice a modified creature"},
        ),
    ]


register("Sephiroth, Fallen Hero", _sephiroth_fallen_hero)
