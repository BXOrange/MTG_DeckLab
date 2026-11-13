from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _charred_graverobber() -> list[AbilitySpec]:
    """When this creature enters, return target outlaw card from your graveyard to your hand.
    Escape—{3}{B}{B}, Exile four other cards from your graveyard. (You may cast this card from your graveyard for its escape cost.)
    This creature escapes with a +1/+1 counter on it.

    Escape and its entry-counter replacement use the shared keyword/entry pipeline.
    """
    return [AbilitySpec('triggered', [EffectSpec('return_from_graveyard', {
        'target_kind': 'graveyard_card', 'destination': 'hand',
        'creature_filter': {'subtype_any': ['Assassin', 'Mercenary', 'Pirate', 'Rogue', 'Warlock']},
    })], trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}})]


register('Charred Graverobber', _charred_graverobber)
