from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tizerus_charger() -> list[AbilitySpec]:
    """Escape—{4}{B}, Exile five other cards from your graveyard. (You may cast this card from your graveyard for its escape cost.)
    This creature escapes with your choice of a +1/+1 counter or a flying counter on it.
    """
    return [AbilitySpec('enter_replacement', [EffectSpec('choose_enter_counter', {
        'escape_only': True,
        'options': [{'kind': '+1/+1', 'count': 1}, {'kind': 'flying', 'count': 1}],
    })])]


register('Tizerus Charger', _tizerus_charger, suppress_keywords=('flying',))
