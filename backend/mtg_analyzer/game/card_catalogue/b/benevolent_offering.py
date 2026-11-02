from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "that player" after "choose an opponent" -- the pick `_request_choose_player` stamped on the spell.
CHOSEN_PLAYER = {"of": "chosen_player"}
#: Tokens each player creates / life gained per creature, as printed.
_SPIRITS_EACH = 3
_LIFE_PER_CREATURE = 2

_SPIRIT = {
    "token_name": "Spirit", "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Spirit"],
    "keywords": ["Flying"], "count": _SPIRITS_EACH,
}


def _benevolent_offering() -> list[AbilitySpec]:
    """Choose an opponent. You and that player each create three 1/1 white Spirit creature tokens with flying.
    Choose an opponent. You gain 2 life for each creature you control and that player gains 2 life for each
    creature they control.

    Two independent "choose an opponent" clauses (RULE 608.2d: chosen as the spell resolves, not targeted), as for
    Intellectual Offering: `_request_choose_player` ``opponents_only`` with the follow-up effects as ``then_effects``.
    The token half uses `create_token`'s ``creators="chosen_player"``; the life half reads each player's own
    ``creatures_you_control`` count (the chosen player is the selector's "you"). The second clause resolves after the
    tokens exist, so they count (rulings 2014-11-07).
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("_request_choose_player", {"opponents_only": True, "then_effects": [
                {"type": "create_token", "params": dict(_SPIRIT)},
                {"type": "create_token", "params": {**_SPIRIT, "creators": "chosen_player"}},
            ]}),
            EffectSpec("_request_choose_player", {"opponents_only": True, "then_effects": [
                {"type": "gain_life", "params": {
                    "count_selector": "creatures_you_control", "count_selector_multiplier": _LIFE_PER_CREATURE}},
                {"type": "gain_life", "params": {
                    "count_selector": "creatures_you_control", "count_selector_multiplier": _LIFE_PER_CREATURE,
                    "player": CHOSEN_PLAYER}},
            ]}),
        ]),
    ]


register("Benevolent Offering", _benevolent_offering)
