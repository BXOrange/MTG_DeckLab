from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "that player" after "choose an opponent" — the pick `_request_choose_player` stamped on the spell.
CHOSEN_PLAYER = {"of": "chosen_player"}


def _intellectual_offering() -> list[AbilitySpec]:
    """Choose an opponent. You and that player each draw three cards.
    Choose an opponent. Untap all nonland permanents you control and all nonland permanents that player
    controls.

    — Peace Offering deck batch. Each "Choose an opponent." is `_request_choose_player` with
    ``opponents_only`` (a lone opponent is taken without a prompt, and the two clauses choose independently,
    as printed); the clauses after it read the pick back through the ``chosen_player`` referent — `draw`'s
    player operand for their three cards, `tap`'s ``selector_player="chosen"`` for the mass untap of that
    player's nonland permanents.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("_request_choose_player", {"opponents_only": True, "then_effects": [
                {"type": "draw", "params": {"count": 3}},
                {"type": "draw", "params": {"count": 3, "player": CHOSEN_PLAYER}},
            ]}),
            EffectSpec("_request_choose_player", {"opponents_only": True, "then_effects": [
                {"type": "tap", "params": {"selector": "nonland_permanents_you_control", "untap": True}},
                {"type": "tap", "params": {
                    "selector": "nonland_permanents_you_control", "untap": True, "selector_player": "chosen"}},
            ]}),
        ]),
    ]


register("Intellectual Offering", _intellectual_offering)
