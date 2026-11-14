from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _species_8472() -> list[AbilitySpec]:
    """Strange new worlds — When this creature enters, you gain life equal to the number of differently named lands you control.
    This creature can't be blocked by artifact creatures.
    This creature can't be the target of abilities from artifact sources your opponents control.
    """
    return [
        AbilitySpec('triggered', [EffectSpec('bind', {
            'name': 'n', 'amount': {'kind': 'count_selector', 'selector': {
                'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'land'}, 'distinct': 'name'}},
            'effects': [{'type': 'gain_life', 'params': {'amount': '$n'}}],
        })], trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}}),
        AbilitySpec('static', [EffectSpec('combat_restriction', {
            'kind': 'cant_be_blocked_by', 'filter': {'card_type': 'artifact'}, 'affects': 'self'})]),
        AbilitySpec('static', [EffectSpec('grant_keyword', {
            'keywords': ['untargetable_by_opponent_artifact_abilities'], 'affects': 'self'})]),
    ]


register('Species 8472', _species_8472)
