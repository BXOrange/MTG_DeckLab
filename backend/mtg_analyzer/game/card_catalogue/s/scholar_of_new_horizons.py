from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scholar_of_new_horizons() -> list[AbilitySpec]:
    """This creature enters with a +1/+1 counter on it.
    {T}, Remove a counter from a permanent you control: Search your library for a Plains card and reveal it. If an opponent controls more lands than you, you may put that card onto the battlefield tapped. If you don't put the card onto the battlefield, put it into your hand. Then shuffle.

    — PLAY-ALL (Counter Blitz). The entry counter is oracle-derived; the cost is `costs.py`'s "remove a counter from a permanent you control".
    `if_else` on ``opponent_controls_more_lands`` (Archaeomancer's Map's condition) over two `search`es for a Plains card: battlefield tapped, else hand.
    With more opposing lands, the searched Plains is revealed and its owner chooses battlefield tapped or hand
    before moving the card and shuffling. Otherwise it goes to hand.
    """
    plains = {"type": "Plains"}
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("if_else", {
                "condition": {"kind": "opponent_controls_more_lands"},
                "then": [{"type": "search", "params": {
                    "criteria": plains, "destination": "battlefield_tapped_or_hand", "count": 1, "optional": True, "reveal": True}}],
                "else": [{"type": "search", "params": {
                    "criteria": plains, "destination": "hand", "count": 1, "optional": True, "reveal": True}}],
            })],
            cost={"text": "{T}, remove a counter from a permanent you control"},
        ),
    ]


register("Scholar of New Horizons", _scholar_of_new_horizons)
