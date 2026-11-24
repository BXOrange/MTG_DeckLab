"""The top of a library divided into two piles (RULE 700.3, 101.4): one player separates, another chooses.

The reveal wording ("reveal the top five cards ... an opponent separates those cards into two piles", Fact or Fiction)
and the look-at wording with a face-down and a face-up pile (Curator of Destinies, Fortune's Favor) share one flow;
who separates (the opponent or the controller) and whether one pile is face down are parameters of it.
"""
from __future__ import annotations

from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import Zone
from .. import continuations
from ..targeting import TargetSpec
from .core import EffectRegistry, GameEffect, _controller_of

#: Who divides the cards (``RevealSplitPilesEffect.divider``); the other player chooses the pile (RULE 101.4).
DIVIDER_OPPONENT = 'opponent'
DIVIDER_CONTROLLER = 'you'
#: ``RevealSplitPilesEffect.opponent`` when the opponent is a RULE 115 target ("target opponent looks at ...").
OPPONENT_TARGETED = 'target'
#: The pile the divider builds card by card; the rest is the other pile. With a face-down pile it is the face-up one.
_FIRST, _SECOND = 'first', 'second'


def _cards(rules, choice):
    owner = rules.state.player_by_id(choice['owner_id'])
    ids = set(choice['card_ids'])
    return [o for o in reversed(owner.library) if o.instance_id in ids]


def _begin(rules, choice, opponent_id):
    """Seat the divider and the chooser once the opponent is known (RULE 101.4)."""
    owner_id = choice['owner_id']
    if choice.get('divider') == DIVIDER_CONTROLLER:
        divider_id, chooser_id = owner_id, opponent_id
    else:
        divider_id, chooser_id = opponent_id, owner_id
    _split(rules, {**choice, 'chooser_id': chooser_id}, divider_id)


def _split(rules, choice, divider_id):
    cards = _cards(rules, choice)
    first = set(choice.get('first_ids', []))
    options = [{'id': str(o.instance_id), 'instance_id': o.instance_id,
                'label': o.name, 'name': o.name} for o in cards if o.instance_id not in first]
    options.append({'id': 'decline', 'label': 'Ersten Stapel abschließen'})
    prompt = ('Wähle die Karten für den offenen Stapel (der Rest bildet den verdeckten)' if choice.get('face_down')
              else 'Wähle die Karten für den ersten Stapel (der Rest bildet den zweiten)')
    rules.open_choice({**choice, 'kind': 'split_revealed_piles', 'player_id': divider_id,
                       'optional': True, 'options': options, 'prompt': prompt})


def _choose_pile(rules, choice):
    first = set(choice.get('first_ids', []))
    cards = _cards(rules, choice)
    face_down = bool(choice.get('face_down'))

    def label(pile):
        members = [o for o in cards if (o.instance_id in first) == (pile == _FIRST)]
        if not members:
            return 'Leerer Stapel'
        if face_down and pile == _SECOND:
            # RULE 700.3 / 406.3: a face-down pile's cards are hidden from the chooser, only its size is known.
            return f'Verdeckter Stapel ({len(members)})'
        return ', '.join(o.name for o in members)

    rules.open_choice({**choice, 'kind': 'take_revealed_pile',
                       'player_id': choice.get('chooser_id') or choice['owner_id'],
                       'optional': False, 'options': [
                           {'id': _FIRST, 'label': label(_FIRST)},
                           {'id': _SECOND, 'label': label(_SECOND)}],
                       'prompt': 'Wähle den Stapel für die Hand; der andere kommt in den Friedhof'})


class RevealSplitPilesEffect(GameEffect):
    """RULE 701.20 / 700.3 / 608.2d: take the top cards of the controller's library, one player divides them into two
    piles and the other chooses which pile goes to the hand (the rest to the graveyard).

    Cards stay in the library during both decisions. Serialized choices carry all identities, both seated players and
    the face-down flag across undo. Empty piles are legal, and no card is drawn by the resulting hand move.

    ``count`` is the literal number of cards, or ``count_selector`` a `continuous.count_selector` argument measured at
    resolution ("x plus 1" from the announced X, the basic land types among your lands). ``reveal`` publishes the cards
    (RULE 701.20) as against "look at" (private to the players who see them). ``divider`` is who separates (the opponent
    or ``'you'``). ``face_down`` makes the second pile face down, so the chooser sees only the first pile's cards.
    ``opponent`` ``'target'`` announces a RULE 115 opponent target; otherwise the controller picks one when several.
    """

    def __init__(self, count=1, source=None, count_selector=None, reveal=True, divider=DIVIDER_OPPONENT,
                 face_down=False, opponent=None):
        super().__init__(source)
        self.count = int(count)
        self.count_selector = count_selector
        self.reveal = bool(reveal)
        self.divider = divider
        self.face_down = bool(face_down)
        self.opponent = opponent
        if opponent == OPPONENT_TARGETED:
            self.target_spec = TargetSpec(kind='opponent', description='Gegner')

    def _measured(self, context, player):
        if self.count_selector is None:
            return self.count
        from .. import continuous  # function-scoped: continuous imports the effect layer
        return int(continuous.count_selector(context.state, player.id, self.count_selector, source=self.source) or 0)

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        opponents = [p for p in context.state.living_players() if p.id != player.id]
        count = self._measured(context, player)
        cards = list(reversed(player.library[-count:])) if count > 0 else []
        if not cards:
            return
        if self.reveal:
            for obj in cards:
                context.state.fire_event(GameEvent(EventType.REVEAL, player_id=player.id,
                    object=obj.name, instance_id=obj.instance_id, from_zone='library'))
        if not opponents:
            return
        choice = {'owner_id': player.id, 'card_ids': [o.instance_id for o in cards],
                  'first_ids': [], 'source_id': getattr(self.source, 'instance_id', None),
                  'divider': self.divider, 'face_down': self.face_down}
        if self.opponent == OPPONENT_TARGETED:
            target = targets[0] if targets else None
            legal = {p.id for p in opponents}
            if getattr(target, 'id', None) not in legal:
                return  # RULE 608.2b: an illegal target does nothing
            _begin(context.engine, choice, target.id)
        elif len(opponents) == 1:
            _begin(context.engine, choice, opponents[0].id)
        else:
            context.engine.open_choice({**choice, 'kind': 'choose_pile_divider', 'player_id': player.id,
                'optional': False, 'prompt': 'Wähle den Gegner für die Stapel',
                'options': [{'id': p.id, 'label': p.name} for p in opponents]})


@continuations.choice('choose_pile_divider', answer=continuations.ANSWER_STR, rule='608.2d')
def _resume_divider(rules, choice, answer):
    if answer not in {o['id'] for o in choice['options']}:
        rules.open_choice(choice)
        raise ValueError('Choose a listed opponent')
    _begin(rules, choice, answer)


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
    if answer not in {_FIRST, _SECOND}:
        rules.open_choice(choice)
        raise ValueError('Choose one of the two piles')
    first = set(choice['first_ids'])
    with rules.state.simultaneous():
        for obj in _cards(rules, choice):
            if (obj.instance_id in first) == (answer == _FIRST):
                rules.return_to_hand(obj)
            else:
                rules.state.player_by_id(obj.owner_id).remove_from_zone(obj, Zone.LIBRARY)
                rules._move_to_graveyard(obj)


EffectRegistry.register('reveal_split_piles', lambda p: RevealSplitPilesEffect(
    count=p.get('count', 1), count_selector=p.get('count_selector'), reveal=p.get('reveal', True),
    divider=p.get('divider', DIVIDER_OPPONENT), face_down=p.get('face_down', False), opponent=p.get('opponent')))
