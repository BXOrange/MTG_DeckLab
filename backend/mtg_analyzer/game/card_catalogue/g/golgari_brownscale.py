"""Golgari Brownscale."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _golgari_brownscale():
    """When this card is put into your hand from your graveyard, you gain 2 life.
Dredge 2 (If you would draw a card, you may mill two cards instead. If you do, return this card from your graveyard to your hand.)
"""
    return [AbilitySpec("triggered", [EffectSpec("gain_life", {"amount": 2})], trigger={
        "event": EventType.RETURNED_TO_HAND, "condition": {"subject": "self"}, "filter": {"from_zone": "graveyard"},
    })]


register("Golgari Brownscale", _golgari_brownscale)
