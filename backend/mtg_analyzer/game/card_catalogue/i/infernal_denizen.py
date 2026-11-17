from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    "At the beginning of your upkeep, sacrifice two Swamps. If you can't, tap this creature, and an opponent may gain control of a creature you control of their choice for as long as this creature remains on the battlefield.\n{T}: Gain control of target creature for as long as this creature remains on the battlefield."
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('gain_control_until_eot', {"target_kind": 'creature', "duration": 'permanent', "haste": False, "untap": False, "while_source": 'on_battlefield'})],
            cost={"text": '{t}'},
            raw_text='{t}: gain control of target creature for as long as ~ remains on the battlefield.',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('sacrifice_with_riders', {"count": 2, "what": 'swamp', "failure": [{'type': 'tap', 'params': {'target_kind': 'source'}}, {'type': '_request_choose_player', 'params': {'opponents_only': True, 'then_effects': [{'type': 'infernal_denizen_offer', 'params': {}}]}}]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'upkeep'}, "phase_relation": 'you'},
            raw_text='',
        ),
    ]


register('Infernal Denizen', _card)
