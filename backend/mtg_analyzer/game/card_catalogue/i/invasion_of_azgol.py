from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_azgol() -> list[AbilitySpec]:
    "(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)\nWhen this Siege enters, target player sacrifices a creature or planeswalker of their choice and loses 1 life."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('sacrifice', {"what": 'creature_or_planeswalker', "target_kind": 'player'}), EffectSpec('lose_life', {"amount": 1, "player": {"of": "target"}})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='',
        ),
    ]


register('Invasion of Azgol', _invasion_of_azgol)


def _ashen_reaper() -> list[AbilitySpec]:
    """Menace
    At the beginning of your end step, put a +1/+1 counter on this creature if a permanent was put into a graveyard from the battlefield this turn.
    """
    return [AbilitySpec('triggered', [EffectSpec('add_counters', {'amount': 1, 'kind': '+1/+1'}, condition={
        'kind': 'event_this_turn', 'min': 1,
        'trigger': {'event': EventType.LEAVES_BATTLEFIELD, 'filter': {'to_zone': 'graveyard'}},
    })], trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'end'}, 'phase_relation': 'you'})]


register('Ashen Reaper', _ashen_reaper)
