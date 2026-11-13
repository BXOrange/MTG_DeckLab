from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _highway_robbery():
    """You may discard a card or sacrifice a land. If you do, draw two cards.
    Plot {1}{R} (You may pay {1}{R} and exile this card from your hand. Cast it as a sorcery on a later turn without paying its mana cost. Plot only as a sorcery.)
    """
    return [AbilitySpec("spell_effect", [EffectSpec("alternative_payment", {
        "alternatives": [
            {"label": "Eine Karte abwerfen", "cost": {"discard": 1}},
            {"label": "Ein Land opfern", "cost": {"sacrifice": "land"}},
        ],
        "effects": [{"type": "draw", "params": {"count": 2}}],
    })])]


register("Highway Robbery", _highway_robbery)
