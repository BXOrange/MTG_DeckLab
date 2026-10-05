from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Opponents at the largest table (four seats) — the most "any number of target opponents" can name.
MAX_OPPONENTS = 3


def _communal_brewing() -> list[AbilitySpec]:
    """When this enchantment enters, any number of target opponents each draw a card. Put an ingredient counter on
    this enchantment, then put an ingredient counter on it for each card drawn this way.
    Whenever you cast a creature spell, that creature enters with X additional +1/+1 counters on it, where X is
    the number of ingredient counters on this enchantment.

    — Peace Offering deck batch. `draw` gained ``target_count``/``target_optional`` (RULE 115.1a, "any number
    of target opponents") and draws for every chosen player; the counters are two `add_counters`, the second
    measuring the new ``targets_count`` amount (one card per chosen opponent — **documented simplification:**
    an opponent with an empty library still counts). The cast clause is an `extra_etb_counter` static
    (``cast_only``) whose count is a live read of the ingredient counters on the source — the counters are on the
    spell *as it enters*, like any entry replacement (RULE 614.1c), not placed by a trigger afterwards.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {
                    "count": 1, "target_kind": "opponent", "target_optional": True,
                    "target_count": MAX_OPPONENTS,
                }),
                EffectSpec("add_counters", {"kind": "ingredient", "count": 1}),
                EffectSpec("add_counters", {"kind": "ingredient", "count": {"kind": "targets_count"}}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec("static", [EffectSpec("extra_etb_counter", {
            "kind": "+1/+1", "cast_only": True,
            "count_selector": {"counters_on": "source", "kind": "ingredient"},
        })]),
    ]


register("Communal Brewing", _communal_brewing)
