"""Compound flickers assembled from existing exile, entry and die machinery."""
from __future__ import annotations

from ...models.game.game_object import Zone
from ...models.game.game_state import DelayedTrigger
from ..continuations import choice
from .core import GameEffect, _controller_of
from .game_status import RollDieEffect


def _exile_batch(context, objects):
    """RULE 608.2c: finish the exile instruction before beginning returns."""
    visits = []
    for obj in list(objects):
        expected = obj.zone_incarnation + 1
        context.engine.exile(obj)
        if obj.zone == Zone.EXILE and obj.zone_incarnation == expected:
            visits.append((obj.instance_id, expected))
    return visits


def _return_batch(context, visits):
    returned = []
    for instance_id, incarnation in visits:
        obj = context.state.find_object(instance_id)
        if obj is not None:
            actual = context.engine.return_from_exile(obj, incarnation, controller_id=obj.owner_id)
            if actual is not None:
                returned.append(actual)
    return returned


class _ReturnCapturedBatchEffect(GameEffect):
    def __init__(self, visits, source=None):
        super().__init__(source)
        self.visits = list(visits)

    def apply(self, context, targets=None):
        _return_batch(context, self.visits)


class _AcrobaticsRoll(RollDieEffect):
    """Existing RULE 706 roller, including its serializable ignore-die choice."""
    HIGH_RESULT = 10  # The printed d20 table's second row begins at ten.

    def __init__(self, visits, player_id, source=None):
        super().__init__(sides=20, source=source)
        self.visits = list(visits)
        self.player_id = player_id

    def _after_roll(self, context, player, targets):
        visits = self.visits
        if context.die_result >= self.HIGH_RESULT:
            # RULE 400.7: the second exile tracks only actual returned NEW visits.
            returned = _return_batch(context, visits)
            visits = _exile_batch(context, returned)
        if visits:
            # RULE 603.7: reuse the existing next-end-step delayed ability.
            context.state.delayed_triggers.append(DelayedTrigger(
                controller_id=self.player_id, step='end', scope='any',
                effects=[_ReturnCapturedBatchEffect(visits, self.source)],
                description="Lae'zel's Acrobatics: die ins Exil geschickten Karten zurückbringen",
            ))


class AcrobaticsEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        # Printed order matters: exiled Pixie Guides cannot modify this roll.
        creatures = [o for o in context.state.permanents()
                     if o.controller_id == player.id and o.is_creature and not o.is_token]
        visits = _exile_batch(context, creatures)
        _AcrobaticsRoll(visits, player.id, self.source).apply(context, targets)


def _open_round(rules, player_id, rounds, source_id):
    candidates = [o for o in rules.state.permanents()
                  if o.controller_id == player_id and o.is_creature]
    if rounds <= 0 or not candidates:
        return
    rules.open_choice({
        'kind': 'flicker_round_selection', 'player_id': player_id,
        'prompt': 'Kreaturen für diesen Durchgang auswählen; anschließend Fertig wählen',
        'source_id': source_id, 'rounds': rounds, 'picked': [],
        'candidates': [(o.instance_id, o.zone_incarnation) for o in candidates],
        'options': [{'id': str(o.instance_id), 'label': o.name, 'instance_id': o.instance_id}
                    for o in candidates] + [{'id': 'done', 'label': 'Fertig'}],
    })


@choice('flicker_round_selection', rule='608.2c')
def _resume_round(rules, choice, answer):
    if answer != 'done':
        option = next((o for o in choice['options'] if o['id'] == answer), None)
        if option is None:
            rules.open_choice(choice)
            raise ValueError('Eine angebotene Kreatur oder Fertig auswählen')
        choice['picked'].append(int(answer))
        choice['options'] = [o for o in choice['options'] if o['id'] != answer]
        rules.open_choice(choice)
        return
    candidates = dict(choice['candidates'])
    chosen = []
    for instance_id in choice['picked']:
        obj = rules.state.find_object(instance_id)
        if (obj is not None and obj.zone == Zone.BATTLEFIELD
                and obj.zone_incarnation == candidates[instance_id]
                and obj.controller_id == choice['player_id'] and obj.is_creature):
            chosen.append(obj)
    _return_batch(rules.context, _exile_batch(rules.context, chosen))
    # Each printed repetition is a fresh selection, including the option of zero.
    _open_round(rules, choice['player_id'], choice['rounds'] - 1, choice['source_id'])


class AnotherRoundEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        x = max(0, int(getattr(self.source, 'x_paid', 0)))
        _open_round(context.engine, player.id, x + 1, getattr(self.source, 'instance_id', None))


EFFECT_FACTORIES = {
    'flicker_repeated_rounds': lambda p: AnotherRoundEffect(),
    'flicker_acrobatics': lambda p: AcrobaticsEffect(),
}
