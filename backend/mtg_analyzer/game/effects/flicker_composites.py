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


def _return_batch(context, visits, after_effects=None, source=None):
    from .battlefield_batches import start_exile_return_batch
    return start_exile_return_batch(context.engine, list(visits),
                                   after_effects=after_effects, source=source)


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
        if context.die_result >= self.HIGH_RESULT:
            # The second exile waits for ALL as-entry choices and admissions.
            _return_batch(context, self.visits,
                          [_AcrobaticsReexileEffect(self.player_id, self.source)], self.source)
        else:
            _schedule_acrobatics(context, self.visits, self.player_id, self.source)


def _schedule_acrobatics(context, visits, player_id, source):
    if visits:
        # RULE 603.7: reuse the existing next-end-step delayed ability.
        context.state.delayed_triggers.append(DelayedTrigger(
            controller_id=player_id, step='end', scope='any',
            effects=[_ReturnCapturedBatchEffect(visits, source)],
            description="Lae'zel's Acrobatics: die ins Exil geschickten Karten zurückbringen",
        ))


class _AcrobaticsReexileEffect(GameEffect):
    def __init__(self, player_id, source=None):
        super().__init__(source)
        self.player_id = player_id

    def apply(self, context, targets=None):
        # RULE 400.7: only successful NEW battlefield visits are exiled again.
        visits = _exile_batch(context, list(targets or []))
        _schedule_acrobatics(context, visits, self.player_id, self.source)


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
    _return_batch(rules.context, _exile_batch(rules.context, chosen),
                  [_NextRoundEffect(choice['player_id'], choice['rounds'] - 1, choice['source_id'])])


class _NextRoundEffect(GameEffect):
    def __init__(self, player_id, rounds, source_id):
        super().__init__()
        self.player_id = player_id
        self.rounds = rounds
        self.source_id = source_id

    def apply(self, context, targets=None):
        # A fresh selection occurs only after this whole pass has entered.
        _open_round(context.engine, self.player_id, self.rounds, self.source_id)


class AnotherRoundEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        x = max(0, int(getattr(self.source, 'x_paid', 0)))
        _open_round(context.engine, player.id, x + 1, getattr(self.source, 'instance_id', None))


EFFECT_FACTORIES = {
    'flicker_repeated_rounds': lambda p: AnotherRoundEffect(),
    'flicker_acrobatics': lambda p: AcrobaticsEffect(),
}


class FortuneScheduleEffect(GameEffect):
    """Capture the attacking Mount's visits for an ordinary end-combat trigger."""
    def apply(self, context, targets=None):
        event = context.trigger_event
        if self.source is None or event is None:
            return
        player = _controller_of(self.source, context)
        source_visit = (self.source.instance_id, event.get('zone_incarnation'))
        saddle_visits = list(event.get('saddled_by_visits') or [])
        context.state.delayed_triggers.append(DelayedTrigger(
            controller_id=player.id, step='end_combat', scope='any',
            effects=[_FortuneChooseEffect(source_visit, saddle_visits, player.id, self.source)],
            description='Fortune: sich und bis zu eine sattelnde Kreatur kurz ins Exil schicken',
        ))


class _FortuneChooseEffect(GameEffect):
    def __init__(self, source_visit, saddle_visits, player_id, source=None):
        super().__init__(source)
        self.source_visit = source_visit
        self.saddle_visits = list(saddle_visits)
        self.player_id = player_id

    def apply(self, context, targets=None):
        candidates = []
        for instance_id, incarnation in self.saddle_visits:
            obj = context.state.find_object(instance_id)
            if (obj is not None and obj.zone == Zone.BATTLEFIELD
                    and obj.zone_incarnation == incarnation and obj.is_creature):
                candidates.append(obj)
        if not candidates:
            _finish_fortune(context.engine, self.source_visit, None)
            return
        context.engine.open_choice({
            'kind': 'fortune_flicker_saddler', 'player_id': self.player_id,
            'source_id': self.source_visit[0], 'source_visit': self.source_visit,
            'saddle_visits': self.saddle_visits,
            'prompt': 'Bis zu eine Kreatur auswählen, die Fortune gesattelt hat',
            'options': [{'id': str(o.instance_id), 'label': o.name, 'instance_id': o.instance_id}
                        for o in candidates] + [{'id': 'done', 'label': 'Keine weitere Kreatur'}],
        })


def _finish_fortune(rules, source_visit, saddler_visit):
    chosen = []
    for visit in (source_visit, saddler_visit):
        if visit is None:
            continue
        instance_id, incarnation = visit
        obj = rules.state.find_object(instance_id)
        if (obj is not None and obj.zone == Zone.BATTLEFIELD
                and obj.zone_incarnation == incarnation):
            chosen.append(obj)
    _return_batch(rules.context, _exile_batch(rules.context, chosen))


@choice('fortune_flicker_saddler', rule='608.2d')
def _resume_fortune(rules, pending, answer):
    if answer not in {o['id'] for o in pending['options']}:
        rules.open_choice(pending)
        raise ValueError('Eine angebotene Kreatur oder Keine weitere Kreatur auswählen')
    visit = None
    if answer != 'done':
        visit = next((v for v in pending['saddle_visits'] if str(v[0]) == answer), None)
    _finish_fortune(rules, pending['source_visit'], visit)


EFFECT_FACTORIES['flicker_fortune_delayed'] = lambda p: FortuneScheduleEffect()
