from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _progenitor_s_icon() -> list[AbilitySpec]:
    """As this artifact enters, choose a creature type.
    {T}: Add one mana of any color.
    {T}: The next spell of the chosen type you cast this turn can be cast as though it had flash.
    """
    # The printed mana ability binds through the native mana scanner.
    return [
        AbilitySpec('enter_replacement', [EffectSpec('choose_creature_type_on_enter', {})]),
        AbilitySpec('activated', [EffectSpec('grant_flash_until_eot', {
            'next_only': True, 'of_chosen_type': True,
        })], cost={'text': '{T}'}),
    ]


register("Progenitor's Icon", _progenitor_s_icon)
