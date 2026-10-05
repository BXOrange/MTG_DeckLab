from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The opponent the `for_each` body is running for (its target), as a search operand — they choose their own
#: land, not the spell's controller.
THAT_OPPONENT = {"of": "target"}


def _tempt_with_discovery() -> list[AbilitySpec]:
    """Tempting offer — Search your library for a land card and put it onto the battlefield. Each opponent may
    search their library for a land card and put it onto the battlefield. For each opponent who searches a
    library this way, search your library for a land card and put it onto the battlefield. Then each player
    who searched a library this way shuffles.

    — Peace Offering deck batch. The same shape as Tempt with Bunnies: your own search, then each opponent is
    asked and searches as themselves (``player`` operand ``{"of": "target"}``, so they — not you — choose the
    land), after which your extra search is the plain default. The search effect already shuffles the library
    it searched. Same documented simplification: your bonus search happens as each opponent accepts.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("search", {"criteria": "Land", "destination": "battlefield", "optional": False}),
            EffectSpec("for_each", {
                "over": {"players": "each_opponent"},
                "effects": [{"type": "pay_cost_then", "params": {
                    "cost": "", "payer": "target", "prompt": "Search for a land and put it onto the battlefield?",
                    "effects": [{"type": "seq", "params": {"effects": [
                        {"type": "search", "params": {
                            "criteria": "Land", "destination": "battlefield", "optional": False,
                            "player": THAT_OPPONENT}},
                        {"type": "search", "params": {
                            "criteria": "Land", "destination": "battlefield", "optional": False}},
                    ]}}],
                }}],
            }),
        ]),
    ]


register("Tempt with Discovery", _tempt_with_discovery)
