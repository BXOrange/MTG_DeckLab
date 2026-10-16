"""Paper-card observations are fresh resolution facts, never printing metadata."""
from __future__ import annotations

import re
from uuid import uuid4

from .core import GameEffect
from .battlefield_batches import start_exile_return_batch
from ..continuations import choice
from ..targeting import TargetSpec
from ...models.game.game_object import Zone
from ...models.game.game_state import DelayedTrigger
from ...parser.oracle.spec import MAX_EFFECT_MAGNITUDE

# RULE 205.3i: all land subtypes, including the nonbasic choices.
LAND_TYPES = ('Cave', 'Desert', 'Forest', 'Gate', 'Island', 'Lair', 'Locus', 'Mine',
              'Mountain', 'Plains', 'Planet', 'Power-Plant', 'Sphere', 'Swamp',
              'Tower', 'Town', "Urza's")


def _controller(context, source):
    return context.acting_player_id or context.resolving_controller_id or source.controller_id


def _reopen(rules, payload, message):
    rules.open_choice(payload)
    raise ValueError(message)


class _StoryEffect(GameEffect):
    def __init__(self, player_id, source=None):
        super().__init__(source)
        self.player_id = player_id

    def apply(self, context, targets=None):
        context.engine.open_choice({
            'kind': 'physical_card_story', 'player_id': self.player_id,
            'prompt': 'Du darfst jetzt eine Geschichte oder interessante Tatsache über die zurückgekehrte Karte erzählen.',
            'options': [{'id': 'shared', 'label': 'Erzählt — 3 Leben erhalten'},
                        {'id': 'decline', 'label': 'Nicht erzählen'}],
        })


@choice('physical_card_story', rule='608.2c')
def _resume_story(rules, payload, answer):
    if answer == 'shared':
        rules.gain_life(rules.state.player_by_id(payload['player_id']), 3)
    elif answer not in (None, 'decline'):
        _reopen(rules, payload, 'Bitte das Erzählen bestätigen oder ablehnen')


class _ReturnStoryCardEffect(GameEffect):
    def __init__(self, visit, player_id, source=None):
        super().__init__(source)
        self.visit, self.player_id = visit, player_id

    def apply(self, context, targets=None):
        start_exile_return_batch(context.engine, [self.visit],
            after_effects=[_StoryEffect(self.player_id, self.source)], source=self.source)


class DriveToWorkEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='permanent', creature_filter={
            'any_of': [{'card_type': 'creature'}, {'subtype': 'Vehicle'}]})

    def apply(self, context, targets=None):
        if not targets:
            return
        obj = targets[0]
        player_id = _controller(context, self.source)
        visit = (obj.instance_id, obj.zone_incarnation + 1)
        context.exile(obj)
        context.state.delayed_triggers.append(DelayedTrigger(player_id, 'end',
            [_ReturnStoryCardEffect(visit, player_id, self.source)], scope='any',
            description='Drive to Work: Karte zurückbringen und optional Geschichte erzählen'))


class MirrorFlickerEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='creature_you_control')

    def apply(self, context, targets=None):
        if not targets:
            return
        obj = targets[0]
        visit = (obj.instance_id, obj.zone_incarnation + 1)
        context.exile(obj)
        context.engine.open_choice({
            'kind': 'physical_environment_measurement', 'property': 'visible_wall_mirrors',
            'player_id': _controller(context, self.source),
            'prompt': 'Bestätige die Anzahl der Wandspiegel, die du von deinem Sitz aus sehen kannst.',
            'minimum': 0, 'maximum': MAX_EFFECT_MAGNITUDE, 'free_text': True,
            'observation_id': str(uuid4()), 'subject': {'name': 'Now You See Me . . .'},
            'exile_visit': visit, 'source_id': getattr(self.source, 'instance_id', None),
            'options': [],
        })


@choice('physical_environment_measurement', rule='107.1')
def _resume_mirrors(rules, payload, answer):
    if (not isinstance(answer, str) or re.fullmatch('[0-9]+', answer) is None
            or len(answer) > len(str(MAX_EFFECT_MAGNITUDE)) or int(answer) > MAX_EFFECT_MAGNITUDE):
        _reopen(rules, payload, 'Bitte eine gültige Anzahl sichtbarer Wandspiegel eingeben')
    start_exile_return_batch(rules, [payload['exile_visit']],
        entry_options={'entry_counters': {'+1/+1': int(answer)}},
        source=rules.state.find_object(payload['source_id']))


class LandfillEffect(GameEffect):
    def apply(self, context, targets=None):
        context.engine.open_choice({
            'kind': 'landfill_land_type', 'player_id': _controller(context, self.source),
            'prompt': 'Wähle einen Landtyp.', 'source_id': getattr(self.source, 'instance_id', None),
            'options': [{'id': name, 'label': name} for name in LAND_TYPES],
        })


def _covered_options(rules, payload):
    selected = set(payload['covered_ids'])
    payload['options'] = [
        {'id': str(iid), 'instance_id': iid,
         'label': ('✓ ' if iid in selected else '') + obj.name}
        for iid, incarnation in payload['candidate_visits']
        if (obj := rules.state.find_object(iid)) is not None
        and obj.zone == Zone.BATTLEFIELD and obj.zone_incarnation == incarnation
    ] + [{'id': 'done', 'label': 'Gemeldete Abdeckung bestätigen (auch keine)'}]
    rules.open_choice(payload)


@choice('landfill_land_type', rule='205.3i')
def _resume_land_type(rules, payload, answer):
    if answer not in LAND_TYPES:
        _reopen(rules, payload, 'Bitte einen angebotenen Landtyp wählen')
    from ..continuous import has_subtype
    subtype = answer.lower().replace('’', "'")
    lands = [obj for obj in rules.state.permanents_controlled_by(payload['player_id'])
             if obj.is_land and has_subtype(obj, subtype)]
    visits = [(obj.instance_id, obj.zone_incarnation + 1) for obj in lands if not obj.is_token]
    with rules.state.simultaneous():
        for obj in lands:
            rules.exile(obj)
    if not visits:
        return
    _covered_options(rules, {
        'kind': 'landfill_covered_report', 'player_id': payload['player_id'],
        'prompt': 'Lass die exilierten Landkarten einzeln aus mindestens 30,48 cm Höhe auf die Spielfläche fallen. Melde danach genau die vollständig bedeckten bleibenden Karten.',
        'source_id': payload['source_id'], 'exile_visits': visits,
        'candidate_visits': [(o.instance_id, o.zone_incarnation) for o in rules.state.permanents()],
        'covered_ids': [],
    })


@choice('landfill_covered_report', rule='608.2c')
def _resume_covered_report(rules, payload, answer):
    if answer != 'done':
        offered = {str(option['id']) for option in payload['options'] if option['id'] != 'done'}
        if answer not in offered:
            _reopen(rules, payload, 'Bitte vollständig bedeckte Karten melden oder die Meldung bestätigen')
        iid = int(answer)
        if iid in payload['covered_ids']:
            payload['covered_ids'].remove(iid)
        else:
            payload['covered_ids'].append(iid)
        _covered_options(rules, payload)
        return
    selected = set(payload['covered_ids'])
    with rules.state.simultaneous():
        for iid, incarnation in payload['candidate_visits']:
            obj = rules.state.find_object(iid)
            if (iid in selected and obj is not None and obj.zone == Zone.BATTLEFIELD
                    and obj.zone_incarnation == incarnation):
                rules.destroy(obj)
    start_exile_return_batch(rules, payload['exile_visits'], entry_options={'tapped': True},
        source=rules.state.find_object(payload['source_id']))


EFFECT_FACTORIES = {
    'drive_to_work': lambda p: DriveToWorkEffect(),
    'mirror_flicker': lambda p: MirrorFlickerEffect(),
    'landfill': lambda p: LandfillEffect(),
}
