from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _identity_thief():
    """Whenever this creature attacks, you may exile another target nontoken creature. If you do, this creature becomes a copy of that creature until end of turn. Return the exiled card to the battlefield under its owner's control at the beginning of the next end step."""
    return [AbilitySpec('triggered', [EffectSpec('blink', {
        'target_kind': 'other_creature', 'creature_filter': {'nontoken': True},
        'departing_copy': {'recipients': 'self', 'duration': 'end_of_turn', 'requires_exile': True},
        'return_step': 'end',
    })], optional=True,
        trigger={'event': EventType.ATTACKS, 'condition': {'subject': 'self'}})]


register('Identity Thief', _identity_thief)
