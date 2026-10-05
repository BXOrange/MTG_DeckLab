from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dread_summons() -> list[AbilitySpec]:
    """Each player mills X cards. For each creature card put into a graveyard this way, you create a tapped 2/2 black Zombie creature token.

    — PLAY-ALL Step 2 (Eternal Might). A `for_each` over every player; each iteration is a `seq` of that player's mill of X (the announced {X}) and
    a `bind` counting the creature cards *that* mill moved (the new ``moved_count`` amount over
    `GameContext.moved_objects`, which a nested composition scopes, so the count has to live in the same
    `seq`) into tapped Zombie tokens for you — the same total as counting after every mill.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("for_each", {
            "over": {"players": "each_player"},
            "effects": [{"type": "seq", "params": {"effects": [
                {"type": "mill", "params": {"count": "x", "target_kind": "player"}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "moved_count", "card_type": "creature"},
                    "effects": [{"type": "create_token", "params": {
                        "count": "$n", "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"],
                        "token_name": "Zombie", "tapped": True,
                    }}],
                }},
            ]}}],
        })]),
    ]


register("Dread Summons", _dread_summons)
