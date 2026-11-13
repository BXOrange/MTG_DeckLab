from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Promotion counters that trigger the damage (the card's "three or more").
PROMOTION_THRESHOLD = 3
#: Damage Beckett deals to each opponent when promoted.
PROMOTION_DAMAGE = 2


def _beckett_mariner_impetuous_ensign() -> list[AbilitySpec]:
    """First strike
    Reckless Behavior — Whenever Beckett Mariner becomes tapped, put a promotion counter on her. Then if there are three or more promotion counters on her, remove those counters and she deals 2 damage to each opponent.

    RULE 603.4 does not apply (no intervening "if"): the threshold is the
    resolution-time "Then if" gate, so the same resolution adds the counter,
    tests the count (RULE 608.2e) and conditionally removes all of that kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "promotion"}),
                EffectSpec("if_else", {
                    "condition": {"kind": "source_counters", "counter": "promotion", "min": PROMOTION_THRESHOLD},
                    "then": [
                        {"type": "remove_counters", "params": {"self_only": True, "kind": "promotion"}},
                        {"type": "damage", "params": {"amount": PROMOTION_DAMAGE, "selector": "each_opponent"}},
                    ],
                }),
            ],
            trigger={"event": EventType.TAPPED, "condition": {"subject": "self"}},
        ),
    ]


register("Beckett Mariner, Impetuous Ensign", _beckett_mariner_impetuous_ensign)
