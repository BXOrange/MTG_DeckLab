from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bane_of_progress() -> list[AbilitySpec]:
    return [AbilitySpec("triggered", [
        EffectSpec("destroy", {"selector": "all_artifacts_and_enchantments"}),
        EffectSpec("bind", {
            "amount": {"kind": "this_way", "tally": "permanents_destroyed_this_way"},
            "effects": [{"type": "add_counters", "params": {
                "amount": "$n", "kind": "+1/+1",
            }}],
        }),
    ], trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}})]


register("Bane of Progress", _bane_of_progress)
