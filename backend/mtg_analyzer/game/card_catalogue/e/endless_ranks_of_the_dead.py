from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _endless_ranks_of_the_dead() -> list[AbilitySpec]:
    """At the beginning of your upkeep, create X 2/2 black Zombie creature tokens, where X is half the number of Zombies you control, rounded down.

    — PLAY-ALL Step 2 (Wretched Ranks). An upkeep trigger whose `bind` measures the Zombies you control with the
    amount spec's ``divide: 2`` (rounded down by default).
    """
    return [AbilitySpec(
        "triggered",
        [EffectSpec("bind", {
            "name": "n",
            "amount": {"kind": "count_selector", "divide": 2, "selector": {
                "zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "subtype": "zombie"}}},
            "effects": [{"type": "create_token", "params": {
                "count": "$n", "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"],
                "token_name": "Zombie",
            }}],
        })],
        trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
    )]


register("Endless Ranks of the Dead", _endless_ranks_of_the_dead)
