from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_lorwyn() -> list[AbilitySpec]:
    "(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)\nWhen this Siege enters, destroy target non-Elf creature an opponent controls with power X or less, where X is the number of lands you control."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('destroy', {"target_kind": 'creature_you_dont_control', "creature_filter": {'without_subtype': 'elf', 'power_le_count_selector': 'lands_you_control'}})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='',
        ),
    ]


register('Invasion of Lorwyn', _invasion_of_lorwyn)
