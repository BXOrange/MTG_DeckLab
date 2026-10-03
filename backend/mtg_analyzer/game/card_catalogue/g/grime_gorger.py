from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grime_gorger() -> list[AbilitySpec]:
    """The attacker chooses cards, each representing a different card type.

    These are resolution choices rather than targets (RULE 115.1d). The
    existing chooser batches the exiles and measures the selected cards.
    """
    return [AbilitySpec(
        "triggered",
        [EffectSpec("choose_objects", {
            "action": "exile", "count": "all", "optional": True,
            "pool_zone": "graveyard", "pool_player_selector": "defending_player",
            "distinct_card_types": True,
            "then_that_many": {"effects": [{"type": "add_counters", "params": {
                "kind": "+1/+1", "count": "x", "target_kind": None,
            }, "condition": {"kind": "source_on_battlefield"}}]},
        })],
        trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
    )]


register("Grime Gorger", _grime_gorger)
