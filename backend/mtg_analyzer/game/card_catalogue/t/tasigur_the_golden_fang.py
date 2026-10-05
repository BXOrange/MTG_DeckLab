from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tasigur_the_golden_fang() -> list[AbilitySpec]:
    """Delve (Each card you exile from your graveyard while casting this spell pays for {1}.)
    {2}{G/U}{G/U}: Mill two cards, then return a nonland card of an opponent's choice from your graveyard to your hand.

    — PLAY-ALL Step 2 (Sultai Arisen). Delve is a keyword fold-in. The ability mills two, then `_request_choose_player`
    (``opponents_only``: you choose the opponent) whose follow-up `return_from_graveyard` is an untargeted ``pick`` made
    by that chosen opponent (new ``chooser="chosen_player"``) over the new ``nonland_card`` graveyard filter. The card
    returns to its owner's (your) hand; with no nonland card in the graveyard nothing is asked.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "mill", "params": {"count": 2}},
                {"type": "_request_choose_player", "params": {
                    "opponents_only": True,
                    "then_effects": [{"type": "return_from_graveyard", "params": {
                        "target_kind": "graveyard_nonland_card", "destination": "hand", "pick": True,
                        "chooser": "chosen_player",
                    }}],
                }},
            ]})],
            cost={"text": "{2}{g/u}{g/u}"},
        ),
    ]


register("Tasigur, the Golden Fang", _tasigur_the_golden_fang)
