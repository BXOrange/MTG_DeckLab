"""Human Torch's combat transformation and optional multicolor payment."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _human_torch():
    """At the beginning of combat on your turn, if you've cast a noncreature spell this turn, Human Torch gains flying, double strike, and haste until end of turn.
Whenever Human Torch attacks, you may pay {R}{G}{W}{U}. If you do, until end of turn, whenever he deals combat damage to an opponent, he deals that much damage to each other opponent."""
    return [
        AbilitySpec('triggered', [EffectSpec('pump', {
            'keywords': ['flying', 'double_strike', 'haste']},
            condition={'kind': 'cast_noncreature_spell_this_turn'})],
            trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'begin_combat'},
                'phase_relation': 'you', 'active_if': {'kind': 'cast_noncreature_spell_this_turn'}}),
        AbilitySpec('triggered', [EffectSpec('pay_cost_then', {
            'cost': '{R}{G}{W}{U}',
            'effects': [{'type': 'human_torch_create_trigger', 'params': {}}],
        })], trigger={'event': EventType.ATTACKS, 'condition': {'subject': 'self'}}),
    ]


register('Human Torch', _human_torch, suppress_keywords=('flying', 'double_strike', 'haste'))
