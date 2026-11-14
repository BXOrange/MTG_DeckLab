from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _kai_winn_faithless_leader() -> list[AbilitySpec]:
    """As Kai Winn enters, choose a nonland card name.
    Whenever an opponent casts a spell with the chosen name or activates an ability of a source with the chosen name, that player loses 3 life.
    """
    return [
        AbilitySpec('enter_replacement', [EffectSpec('choose_card_name_on_enter', {
            'card_filter': {'without_type': 'land'}})]),
        AbilitySpec('triggered', [EffectSpec('lose_life', {'amount': 3, 'selector': 'event_player'})],
            trigger={'event': [EventType.SPELL_CAST, EventType.ACTIVATED_ABILITY, EventType.MANA_ABILITY_ACTIVATED],
                'condition': {'subject': 'global'}, 'caster_relation': 'opponent', 'source_name_chosen': True}),
    ]


register('Kai Winn, Faithless Leader', _kai_winn_faithless_leader)
