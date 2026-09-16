from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wickersmiths_tools() -> list[AbilitySpec]:
    """Whenever one or more -1/-1 counters are put on a creature, put a
    charge counter on this artifact.
    {T}: Add one mana of any color.
    {5}, {T}, Sacrifice this artifact: Create X tapped 2/2 colorless
    Scarecrow artifact creature tokens, where X is the number of charge
    counters on this artifact.

    The mana ability folds in from `mana_abilities_for` (independent of
    catalogue registration). Authored here: the Flourishing Defenses
    `EventType.COUNTER` charge-counter trigger (unscoped), and the
    sacrifice ability whose token count is ``count_selector=
    "charge_counters_on_source"`` (`continuous.count_selector`, resolved
    once as the ability resolves — the card's only ruling).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "charge"})],
            trigger={
                "event": "COUNTER",
                "filter": {"kind": "-1/-1", "recipient_is_creature": True},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "power": 2, "toughness": 2, "colors": [], "subtypes": ["Scarecrow"],
                "token_name": "Scarecrow", "is_artifact": True, "tapped": True,
                "count_selector": "charge_counters_on_source",
            })],
            cost={"text": "{5}, {T}, Sacrifice ~"},
        ),
    ]


register("Wickersmith's Tools", _wickersmiths_tools)
