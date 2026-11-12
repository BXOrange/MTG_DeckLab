"""The Salubrious Philosopher."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _salubrious():
    """If you would draw a card, you may instead choose mana base, removal, or win condition and reveal cards from the top of your library until you reveal a card of the chosen kind. Put that card into your hand and the rest on the bottom of your library in a random order. (Mana base cards add mana. Removal cards are instants and sorceries that can damage, destroy, or exile opposing permanents. Win conditions cost 6 or more mana.)"""
    return [AbilitySpec("replacement", [EffectSpec("optional_draw_dig", {
        "random_order": True, "categories": "salubrious",
    })])]


register("The Salubrious Philosopher", _salubrious)
