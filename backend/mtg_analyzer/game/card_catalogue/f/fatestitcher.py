from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fatestitcher() -> list[AbilitySpec]:
    '{T}: You may tap or untap another target permanent.\nUnearth {U} ({U}: Return this card from your graveyard to the battlefield. It gains haste. Exile it at the beginning of the next end step or if it would leave the battlefield. Unearth only as a sorcery.)'
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('tap', {"target_kind": 'permanent', "creature_filter": {'not_reference': True}, "choose_tap_or_untap": True, "optional": True})],
            cost={"text": '{T}'},
            raw_text='',
        ),
    ]


register('Fatestitcher', _fatestitcher)
