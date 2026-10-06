"""Public library reveals divided into piles by another player."""
from __future__ import annotations

from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import Zone
from .. import continuations
from .core import EffectRegistry, GameEffect, _controller_of


def _cards(rules, choice):
    owner = rules.state.player_by_id(choice['owner_id'])
    ids = set(choice['card_ids'])
    return [o for o in reversed(owner.library) if o.instance_id in ids]


def _split(rules, choice, divider_id):
    cards = _cards(rules, choice)
    first = set(choice.get('first_ids', []))
    options = [{'id': str(o.instance_id), 'instance_id': o.instance_id,
                'label': o.name, 'name': o.name} for o in cards if o.instance_id not in first]
    options.append({'id': 'decline', 'label': 'Ersten Stapel abschließen'})
    rules.open_choice({**choice, 'kind': 'split_revealed_piles', 'player_id': divider_id,
                       'optional': True, 'options': options,
                       'prompt': 'Wähle die Karten für den ersten Stapel (der Rest bildet den zweiten)'})


def _choose_pile(rules, choice):
    first = set(choice.get('first_ids', []))
    cards = _cards(rules, choice)
    def label(in_first):
        names = [o.name for o in cards if (o.instance_id in first) == in_first]
        return ', '.join(names) if names else 'Leerer Stapel'
    rules.open_choice({**choice, 'kind': 'take_revealed_pile', 'player_id': choice['owner_id'],
                       'optional': False, 'options': [
                           {'id': 'first', 'label': label(True)},
                           {'id': 'second', 'label': label(False)}],
                       'prompt': 'Wähle den Stapel für deine Hand; der andere kommt in den Friedhof'})


class RevealSplitPilesEffect(GameEffect):
    """RULE 701.28 / 608.2d: reveal, opponent divides, controller chooses.

    Revealed cards stay in the library during both decisions. Serialized
    choices carry all identities and the resolving controller across undo.
    Empty piles are legal, and no card is drawn by the resulting hand move.
    """

    def __init__(self, count=1, source=None):
        super().__init__(source)
        self.count = int(count)

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        opponents = [p for p in context.state.living_players() if p.id != player.id]
        cards = list(reversed(player.library[-self.count:])) if self.count > 0 else []
        if not cards:
            return
        for obj in cards:
            context.state.fire_event(GameEvent(EventType.REVEAL, player_id=player.id,
                object=obj.name, instance_id=obj.instance_id, from_zone='library'))
        if not opponents:
            return
        choice = {'owner_id': player.id, 'card_ids': [o.instance_id for o in cards],
                  'first_ids': [], 'source_id': getattr(self.source, 'instance_id', None)}
        if len(opponents) == 1:
            _split(context.engine, choice, opponents[0].id)
        else:
            context.engine.open_choice({**choice, 'kind': 'choose_pile_divider', 'player_id': player.id,
                'optional': False, 'prompt': 'Wähle den Gegner, der die aufgedeckten Karten aufteilt',
                'options': [{'id': p.id, 'label': p.name} for p in opponents]})


@continuations.choice('choose_pile_divider', answer=continuations.ANSWER_STR, rule='608.2d')
def _resume_divider(rules, choice, answer):
    if answer not in {o['id'] for o in choice['options']}:
        rules.open_choice(choice)
        raise ValueError('Choose a listed opponent')
    _split(rules, choice, answer)


@continuations.choice('split_revealed_piles', answer=continuations.ANSWER_INT, rule='608.2d')
def _resume_split(rules, choice, answer):
    if answer is None:
        _choose_pile(rules, choice)
        return
    if answer not in {o.get('instance_id') for o in choice['options'] if 'instance_id' in o}:
        rules.open_choice(choice)
        raise ValueError('Choose a revealed card')
    updated = {**choice, 'first_ids': [*choice['first_ids'], answer]}
    if len(updated['first_ids']) == len(_cards(rules, updated)):
        _choose_pile(rules, updated)
    else:
        _split(rules, updated, choice['player_id'])


@continuations.choice('take_revealed_pile', answer=continuations.ANSWER_STR, rule='608.2d')
def _resume_take(rules, choice, answer):
    if answer not in {'first', 'second'}:
        rules.open_choice(choice)
        raise ValueError('Choose one of the two piles')
    first = set(choice['first_ids'])
    with rules.state.simultaneous():
        for obj in _cards(rules, choice):
            if (obj.instance_id in first) == (answer == 'first'):
                rules.return_to_hand(obj)
            else:
                rules.state.player_by_id(obj.owner_id).remove_from_zone(obj, Zone.LIBRARY)
                rules._move_to_graveyard(obj)


EffectRegistry.register('reveal_split_piles', lambda p: RevealSplitPilesEffect(count=p.get('count', 1)))
