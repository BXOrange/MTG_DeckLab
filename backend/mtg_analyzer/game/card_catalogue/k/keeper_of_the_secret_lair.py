from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

# Actual Secret Lair printings, not Universes Within (SLX) reprints or an
# ordinary printing of a card that also appeared in a Secret Lair product.
_SECRET_LAIR_SET_CODES = ('sld', 'slp', 'slu', 'slc', 'slz')


def _keeper_of_the_secret_lair() -> list[AbilitySpec]:
    """Flash
    You may cast Secret Lair spells as though they had flash.
    Secret Lair spells you cast cost {1} less to cast.
    """
    return [
        AbilitySpec('static', [EffectSpec('flash_permission', {'set_codes': list(_SECRET_LAIR_SET_CODES)})]),
        AbilitySpec('static', [EffectSpec('cost_reduction', {
            'generic': 1, 'set_codes': list(_SECRET_LAIR_SET_CODES),
        })]),
    ]


register('Keeper of the Secret Lair', _keeper_of_the_secret_lair)
