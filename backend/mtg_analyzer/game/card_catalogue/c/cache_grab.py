from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cache_grab() -> list[AbilitySpec]:
    """Mill four cards. You may put a permanent card from among the cards milled this way into your hand. If you control a Squirrel or returned a Squirrel card to your hand this way, create a Food token. (To mill four cards, put the top four cards of your library into your graveyard. A Food token is an artifact with "{2}, {T}, Sacrifice this token: You gain 3 life.")
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('mill_recover_permanent_subtype_bonus', {}),
            ],
        ),
    ]


register('Cache Grab', _cache_grab)
