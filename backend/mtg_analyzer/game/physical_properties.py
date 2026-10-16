"""Player-observed properties of a particular physical printing and face.

These are facts about printed objects, never estimates from Oracle layout.
Unsanctioned FAQ: a line counts if it contains non-italicized rules text.
"""
from __future__ import annotations

import inspect
import re
from functools import wraps

from ..parser.oracle.spec import MAX_EFFECT_MAGNITUDE
from . import continuations

PROPERTY = 'printed_rules_lines'
# Match the engine's existing numeric transport/IR bound, not a Magic rule limit.
MAXIMUM = MAX_EFFECT_MAGNITUDE
PROMPT = 'Anzahl gedruckter Regeltextzeilen bestätigen'


def subject(obj, face='front'):
    printed = obj.physical_printing
    selected = printed.get(face) or printed['front']
    return {'printing_id': printed['printing_id'], 'face': face, **selected}


def key(obj, face='front'):
    return (obj.physical_printing['printing_id'], face, PROPERTY)


def measured(state, obj, face='front'):
    return state.physical_property_facts.get(key(obj, face))


def observers(state, player_id):
    """Only active abilities that can actually watch this player's cast."""
    return any(
        o.controller_id == player_id and not o.loses_all_abilities
        and any(a.trigger_event == 'SPELL_CAST' and getattr(a, 'printed_rules_lines_required', False)
                for a in o.triggered_abilities)
        for o in state.permanents()
    )


def cast_lines(state, obj, player_id):
    face = getattr(obj, '_cast_physical_face', 'front')
    value = 0 if face == 'face_down' else measured(state, obj, face)
    if value is None and observers(state, player_id) and not getattr(state, '_physical_cast_validation', False):
        raise ValueError('Printed rules-text lines must be measured before casting this spell')
    return value


def request(rules, obj, player_id, face='front', *, cast=False):
    rules.open_choice({'kind': 'physical_property_measurement', 'property': PROPERTY,
                       'minimum': 0, 'maximum': MAXIMUM, 'free_text': True,
                       'player_id': player_id, 'prompt': PROMPT,
                       'subject': subject(obj, face), 'fact_key': key(obj, face),
                       'cast_announcement': cast, 'options': [],
                       **({'fact_reporter_id': obj.owner_id} if cast and obj.zone is None else {})})


@continuations.choice('physical_property_measurement', rule='107.1')
def _resume_physical_property(rules, choice, answer):
    # RulesEngine claims the choice before dispatch. Invalid factual input
    # must leave it pending, unlike number choices with a default answer.
    if (not isinstance(answer, str) or re.fullmatch(r'[0-9]+', answer) is None
            or len(answer) > len(str(MAXIMUM)) or int(answer) > MAXIMUM):
        rules.open_choice(choice)
        raise ValueError('Bitte eine gültige Anzahl gedruckter Regeltextzeilen eingeben')
    rules.state.physical_property_facts[tuple(choice['fact_key'])] = int(answer)


def choice_decider(state, choice):
    # Reporting an owner's private outside-game printing is a factual
    # observation, not a gameplay choice transferred by controlling a turn.
    if choice.get('kind') == 'physical_property_measurement' and choice.get('fact_reporter_id'):
        return choice['fact_reporter_id']
    return state.decider_for(choice['player_id'])


def encode(value):
    from ..models.game.game_object import GameObject
    from ..models.game.player import Player
    if isinstance(value, GameObject):
        return {'object_ref': value.instance_id, 'incarnation': value.zone_incarnation}
    if isinstance(value, Player):
        return {'player_ref': value.id}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    return value


def decode(state, value):
    if isinstance(value, dict) and 'object_ref' in value:
        obj = state.find_object(value['object_ref'])
        if (obj is None or obj.zone_incarnation != value['incarnation']
                or state.player_by_id(obj.owner_id).has_lost):
            raise ValueError('Das angekündigte Objekt befindet sich nicht mehr in derselben Zone')
        return obj
    if isinstance(value, dict) and 'player_ref' in value:
        player = state.player_by_id(value['player_ref'])
        if player is None or player.has_lost:
            raise ValueError('Der angekündigte Spieler ist nicht mehr im Spiel')
        return player
    if isinstance(value, list):
        return [decode(state, v) for v in value]
    if isinstance(value, dict):
        return {k: decode(state, v) for k, v in value.items()}
    return value


_COST_OBJECT_ARGUMENTS = frozenset({
    'sacrifice_choice', 'sacrifice_choices', 'graveyard_sacrifice_choice',
    'graveyard_exile_choices', 'discard_choices', 'teamwork_choices', 'tap_choices',
})


def cost_objects(state, params):
    refs = {}
    for name in _COST_OBJECT_ARGUMENTS:
        value = params.get(name)
        for iid in value if isinstance(value, (list, tuple)) else [value]:
            if isinstance(iid, int) and (obj := state.find_object(iid)) is not None:
                refs[iid] = obj.zone_incarnation
    return refs


def preflight(cast):
    signature = inspect.signature(cast)

    @wraps(cast)
    def announce(engine, player, obj, *args, **kwargs):
        bound = signature.bind(engine, player, obj, *args, **kwargs)
        bound.apply_defaults()
        params = {k: v for k, v in bound.arguments.items() if k not in {'self', 'player', 'obj'}}
        face = params.get('face', 'front')
        # Face-down spells have no face-up rules text (RULE 708.2).
        if (not getattr(engine.state, '_physical_cast_validation', False)
                and face != 'face_down' and observers(engine.state, player.id) and measured(engine.state, obj, face) is None):
            if engine.state.pending_choice is not None:
                raise ValueError('Zuerst die offene Entscheidung abschließen')
            validate_cast(engine, player, obj, params)
            engine.state.pending_physical_cast = {
                'player_id': player.id, 'object': encode(obj), 'kwargs': encode(params),
                'cost_objects': cost_objects(engine.state, params),
            }
            request(engine.rules, obj, player.id, face, cast=True)
            return None
        previous = getattr(obj, '_cast_physical_face', None)
        obj._cast_physical_face = face
        try:
            return cast(engine, player, obj, *args, **kwargs)
        finally:
            if previous is None:
                obj.__dict__.pop('_cast_physical_face', None)
            else:
                obj._cast_physical_face = previous
    return announce


def validate_cast(engine, player, obj, params):
    """Pure preflight against a disposable clone using the complete cast path.

    It validates every target group, mode and actual resource payment without
    mutating the live face, mana, gifts, events or choices. No physical fact is
    fabricated: the trial event carries an unknown count and is discarded.
    """
    from .game_engine import GameEngine
    trial = GameEngine(engine.state.clone())
    trial.state._physical_cast_validation = True
    trial.state.pending_choice = None
    trial.cast_spell(trial.state.player_by_id(player.id),
                     decode(trial.state, encode(obj)), **decode(trial.state, encode(params)))


def resume_cast(engine):
    frame = engine.state.pending_physical_cast
    engine.state.pending_physical_cast = None
    player = engine.state.player_by_id(frame['player_id'])
    try:
        obj = decode(engine.state, frame['object'])
        params = decode(engine.state, frame['kwargs'])
        if any((candidate := engine.state.find_object(iid)) is None
               or candidate.zone_incarnation != incarnation
               for iid, incarnation in frame.get('cost_objects', {}).items()):
            raise ValueError('An announced cost object has changed zones')
        validate_cast(engine, player, obj, params)
    except ValueError:
        if frame.get('resolution_play'):
            engine.rules._finish_resolution_play_permission()
            engine._finish_resolution_play()
        # A legal observation does not force a now-illegal cast. Abandon the
        # announcement without costs or a retry loop in transactional APIs.
        return None
    if frame.get('resolution_play'):
        engine.rules.open_choice(frame['resolution_play'])
        return engine.play_resolution_card(player, obj, **params)
    return engine.cast_spell(player, obj, **params)
