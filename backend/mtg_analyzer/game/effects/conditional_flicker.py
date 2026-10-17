"""Optional immediate returns and optional payments on exact delayed visits."""
from .core import GameEffect, _controller_of
from .battlefield_batches import start_exile_return_batch
from .flicker_composites import _exile_batch
from ..continuations import choice
from ..costs import parse_activation_cost
from ..targeting import TargetSpec
from ...models.game.game_state import DelayedTrigger


class ReturnCapturedExileVisitsEffect(GameEffect):
    def __init__(self, visits, entry_options=None, source=None):
        super().__init__(source)
        self.visits = list(visits)
        self.entry_options = dict(entry_options or {})

    def apply(self, context, targets=None):
        start_exile_return_batch(context.engine, self.visits,
            entry_options=self.entry_options, source=self.source)


class _PayToKeepExiledEffect(GameEffect):
    def __init__(self, visits, cost, source=None):
        super().__init__(source)
        self.visits, self.cost = list(visits), cost

    def apply(self, context, targets=None):
        context.engine._request_pay_cost_then(
            _controller_of(self.source, context), parse_activation_cost(self.cost), [], self.source,
            else_effect_specs=[{'type': 'return_captured_exile_visits', 'params': {'visits': self.visits}}],
        )


class ConditionalFlickerEffect(GameEffect):
    def __init__(self, policy, target_kind='creature', creature_filter=None,
                 optional=False, cost=None, source=None):
        super().__init__(source)
        if policy not in {'immediate_or_countered', 'unless_paid', 'unless_gift_promised'}:
            raise ValueError('Unknown flicker return policy')
        self.policy, self.cost = policy, cost
        self.target_spec = TargetSpec(kind=target_kind, creature_filter=creature_filter, optional=optional)

    def apply(self, context, targets=None):
        visits = _exile_batch(context, targets or [])
        if not visits:
            return
        player = _controller_of(self.source, context)
        if self.policy == 'immediate_or_countered':
            context.engine.open_choice({
                'kind': 'flicker_return_timing', 'player_id': player.id,
                'source_id': getattr(self.source, 'instance_id', None), 'visits': visits,
                'prompt': 'Die Karte jetzt zurückbringen oder im nächsten Endsegment mit Marken?',
                'options': [{'id': 'now', 'label': 'Jetzt zurückbringen'},
                            {'id': 'later', 'label': 'Im Endsegment mit Vigilance und Lifelink'}],
            })
        else:
            if self.policy == 'unless_gift_promised' and self.source.gift_promised:
                return
            effect = (_PayToKeepExiledEffect(visits, self.cost, self.source)
                      if self.policy == 'unless_paid' else
                      ReturnCapturedExileVisitsEffect(visits, {'entry_counters': {'+1/+1': 1}}, self.source))
            context.state.delayed_triggers.append(DelayedTrigger(
                player.id, 'end', [effect], scope='any'))


@choice('flicker_return_timing', rule='608.2c')
def _resume_return_timing(rules, payload, answer):
    if answer not in ('now', 'later'):
        rules.open_choice(payload)
        raise ValueError('Bitte den Rückkehrzeitpunkt wählen')
    source = rules.state.find_object(payload['source_id'])
    if answer == 'now':
        start_exile_return_batch(rules, payload['visits'], source=source)
    else:
        effect = ReturnCapturedExileVisitsEffect(payload['visits'],
            {'entry_counters': {'vigilance': 1, 'lifelink': 1}}, source)
        rules.state.delayed_triggers.append(DelayedTrigger(
            payload['player_id'], 'end', [effect], scope='any'))


EFFECT_FACTORIES = {
    'conditional_flicker': lambda p: ConditionalFlickerEffect(
        p.get('policy'), p.get('target_kind', 'creature'), p.get('creature_filter'),
        bool(p.get('optional')), p.get('cost')),
    'return_captured_exile_visits': lambda p: ReturnCapturedExileVisitsEffect(
        p.get('visits', []), p.get('entry_options')),
}
