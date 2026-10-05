from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _syphon_flesh() -> list[AbilitySpec]:
    """Each other player sacrifices a creature of their choice. You create a 2/2 black Zombie creature token for each creature sacrificed this way.

    — PLAY-ALL Step 2 (Wretched Ranks). Bellowing Mauler's `choose_player_objects` (every opponent picks their own
    creature, simultaneously, RULE 101.4) with a ``then_that_many`` tail: the ``"x"`` sentinel is the number of
    creatures actually sacrificed, which sizes the Zombie tokens you create.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("choose_player_objects", {
        "action": "sacrifice", "player_scope": "each_opponent",
        "permanent_filter": {"creature": True},
        "then_that_many": {"effects": [{"type": "create_token", "params": {
            "count": "x", "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"],
            "token_name": "Zombie",
        }}]},
    })])]


register("Syphon Flesh", _syphon_flesh)
