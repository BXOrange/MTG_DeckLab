from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    "Target opponent chooses a number. You may have that player lose that much life. If you don't, that player sacrifices all but that many permanents of their choice."
    return [
        AbilitySpec(
            'spell_effect',
            [EffectSpec('choice_of_damnations', {})],
            raw_text='',
        ),
    ]


register('Choice of Damnations', _card)
