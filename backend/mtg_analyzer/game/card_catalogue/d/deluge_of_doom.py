from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deluge_of_doom() -> list[AbilitySpec]:
    """All creatures get -X/-X until end of turn, where X is the number of card types among cards in your graveyard.

    — PLAY-ALL (Death Toll). Mutilate's shape: a `bind` measuring the distinct card types (RULE 205.2a, the structured
    ``distinct: card_type`` selector Delirium uses) in your graveyard, negated, into a group `pump`; counted once on resolution.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("bind", {
        "name": "n",
        "amount": {"kind": "count_selector", "multiply": -1, "selector": {
            "zone": "graveyard", "of": "you", "distinct": "card_type"}},
        "effects": [{"type": "pump", "params": {"power": "$n", "toughness": "$n", "selector": "all_creatures"}}],
    })])]


register("Deluge of Doom", _deluge_of_doom)
