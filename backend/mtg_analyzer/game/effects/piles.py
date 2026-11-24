"""The top of a library divided into two piles (RULE 700.3, 101.4): one player separates, another chooses.

The reveal wording ("reveal the top five cards ... an opponent separates those cards into two piles", Fact or Fiction)
and the look-at wording with a face-down and a face-up pile (Curator of Destinies, Fortune's Favor) share one flow;
who separates (the opponent or the controller) and whether one pile is face down are parameters of it.

``SeparatePilesEffect`` (PAR-292 M22) runs the same choice flow over objects in a public zone instead: a player's
creatures or permanents, a graveyard's creature cards, the cards a preceding clause exiled. Who separates and who chooses are
roles (``you`` the controller, ``owner`` the player the objects belong to, ``opponent`` an opponent of that owner), and each
pile has a fate (destroy, sacrifice, exile, battlefield, hand, graveyard, tap) applied once every pool has been chosen.
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
#: ``SeparatePilesEffect.pool`` / the choice's ``pool``: the cards are objects in a public zone, found by id, rather than
#: the top of a library.
POOL_OBJECTS = 'objects'
#: Who separates / chooses over a pool of objects (RULE 101.4): the controller, the player the objects belong to, or an
#: opponent of that player (the owner picks when several, "one of their opponents of their choice").
ROLE_YOU, ROLE_OWNER, ROLE_OPPONENT = 'you', 'owner', 'opponent'
#: What a pile becomes. The chosen pile's fate is applied first, then the other's (the printed order of every card).
FATE_DESTROY, FATE_DESTROY_NO_REGEN = 'destroy', 'destroy_no_regen'
FATE_SACRIFICE, FATE_EXILE, FATE_BATTLEFIELD = 'sacrifice', 'exile', 'battlefield'
FATE_HAND, FATE_GRAVEYARD, FATE_TAP = 'hand', 'graveyard', 'tap'
#: PAR-292 M23 (Truth or Tale): ``RevealSplitPilesEffect.fate`` -- the chosen pile yields ONE card of its owner's pick for the
#: hand and every other revealed card goes to the bottom of the library in any order, in place of the plain "chosen pile to
#: hand, the other to the graveyard" (Fact or Fiction).
FATE_PICK_ONE_REST_BOTTOM = 'pick_one_rest_bottom'
#: PAR-292 M23 (Brilliant Ultimatum): "you may play lands and cast spells from one of those piles ... without paying
#: its mana cost" -- the chosen pile's cards stay exiled and are offered to the controller during this resolution (RULE
#: 608.2g, 118.9); the other pile stays exiled.
FATE_PLAY_FREE = 'play_free'
#: Fate -> the German clause the chooser's prompt names ("Wähle den Stapel, der ...").
_FATE_PROMPTS = {
    FATE_DESTROY: 'zerstört wird', FATE_DESTROY_NO_REGEN: 'zerstört wird (keine Regeneration)',
    FATE_SACRIFICE: 'geopfert wird', FATE_EXILE: 'ins Exil kommt', FATE_BATTLEFIELD: 'aufs Schlachtfeld kommt',
    FATE_HAND: 'auf die Hand kommt', FATE_GRAVEYARD: 'in den Friedhof kommt', FATE_TAP: 'getappt wird',
    FATE_PLAY_FREE: 'gespielt bzw. kostenlos gewirkt werden darf',
}
#: Which objects a pool holds, and whose.
SET_CREATURES, SET_PERMANENTS, SET_NONTOKEN_LANDS = 'creatures', 'permanents', 'nontoken_lands'
SET_GRAVEYARD_CREATURES, SET_EXILED_THIS_WAY = 'graveyard_creature_cards', 'exiled_this_way'
OWNERS_TARGET_PLAYER, OWNERS_EACH_OPPONENT, OWNERS_EACH_PLAYER, OWNERS_YOU = 'target_player', 'each_opponent', 'each_player', 'you'


def _cards(rules, choice):
    if choice.get('pool') == POOL_OBJECTS:
        found = (rules.state.find_object(i) for i in choice['card_ids'])
        return [o for o in found if o is not None]
    owner = rules.state.player_by_id(choice['owner_id'])
    ids = set(choice['card_ids'])
    return [o for o in reversed(owner.library) if o.instance_id in ids]


def _begin(rules, choice, opponent_id):
    """Seat the divider and the chooser once the opponent is known (RULE 101.4)."""
    owner_id = choice['owner_id']
    if choice.get('pool') == POOL_OBJECTS:
        _seat(rules, {**choice, 'opponent_id': opponent_id})
        return
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


def _take_prompt(choice):
    if choice.get('pool') != POOL_OBJECTS:
        if choice.get('fate') == FATE_PICK_ONE_REST_BOTTOM:
            return 'Wähle den Stapel, aus dem eine Karte auf die Hand kommt; alle anderen Karten kommen nach unten'
        return 'Wähle den Stapel für die Hand; der andere kommt in den Friedhof'
    return f"Wähle den Stapel, der {_FATE_PROMPTS[choice['chosen_fate']]}"


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
                       'prompt': _take_prompt(choice)})


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
                 face_down=False, opponent=None, fate=None):
        super().__init__(source)
        self.fate = fate
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
                  'divider': self.divider, 'face_down': self.face_down, 'fate': self.fate}
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
    chosen = [o for o in _cards(rules, choice) if (o.instance_id in first) == (answer == _FIRST)]
    chosen_ids = {o.instance_id for o in chosen}
    others = [o for o in _cards(rules, choice) if o.instance_id not in chosen_ids]
    if choice.get('pool') == POOL_OBJECTS:
        _pool_done(rules, choice, [o.instance_id for o in chosen], [o.instance_id for o in others])
        return
    if choice.get('fate') == FATE_PICK_ONE_REST_BOTTOM:
        _pick_one_rest_bottom(rules, choice, chosen, chosen + others)
        return
    with rules.state.simultaneous():
        _apply_fate(rules, chosen, FATE_HAND, choice)
        _apply_fate(rules, others, FATE_GRAVEYARD, choice)


def _pick_one_rest_bottom(rules, choice, chosen, everything):
    """RULE 608.2d / 401.4: the owner puts one card of the chosen pile into their hand, then every other revealed card goes
    to the bottom of the library in an order they choose (the cards are still in the library, so the ordering prompt moves
    them under it). An empty chosen pile gives no card and the whole batch goes down."""
    owner = rules.state.player_by_id(choice['owner_id'])
    every_id = [o.instance_id for o in everything]
    if not chosen:
        rules._handle_rest_inspected(owner, every_id, 'library_bottom_order')
        return
    rules._request_choose_objects(
        owner, chosen, 'library_to_hand', count=1, prompt='Wähle eine Karte des Stapels für deine Hand',
        rest_ids=every_id, rest_destination='library_bottom_order')


def _apply_fate(rules, objects, fate, choice):
    """Carry out one pile's fate on ``objects`` together (RULE 608.2c: every object of the instruction at once)."""
    if not objects:
        return  # RULE 700.3: a pile may be empty
    if fate == FATE_HAND:
        for obj in objects:
            rules.return_to_hand(obj)
    elif fate == FATE_GRAVEYARD:
        for obj in objects:
            owner = rules.state.player_by_id(obj.owner_id)
            zone_cards = owner.zones.get(obj.zone)
            if zone_cards is not None and obj in zone_cards:
                owner.remove_from_zone(obj, obj.zone)
            rules._move_to_graveyard(obj)
    elif fate in (FATE_DESTROY, FATE_DESTROY_NO_REGEN):
        # RULE 701.8 / 701.19: an indestructible permanent survives, a regeneration shield saves it unless "can't be
        # regenerated" was printed; `RulesEngine.destroy` decides each.
        rules._remove_simultaneously(
            objects, lambda o: rules.destroy(o, can_be_regenerated=fate == FATE_DESTROY))
    elif fate == FATE_SACRIFICE:
        rules._sacrifice_simultaneously(objects)  # RULE 701.21: the controller of each permanent sacrifices it
    elif fate == FATE_EXILE:
        for obj in objects:
            rules.exile(obj)
    elif fate == FATE_BATTLEFIELD:
        for obj in objects:
            rules.return_from_graveyard(obj, 'battlefield', controller_id=choice['controller_id'])
    elif fate == FATE_TAP:
        for obj in objects:
            if obj.zone == Zone.BATTLEFIELD:
                obj.tapped = True
    # FATE_PLAY_FREE moves nothing: `_finish` offers the pile once every fate is through.


def _object_pool(context, controller, owner, which):
    """The objects ``owner`` separates for the printed set, in zone order (RULE 700.3)."""
    from ..rules.damage_death_mixin import _matches_permanent_type  # function-scoped: rules <-> effects cycle
    if which in (SET_CREATURES, SET_PERMANENTS, SET_NONTOKEN_LANDS):
        what = {SET_CREATURES: 'creature', SET_PERMANENTS: 'permanent', SET_NONTOKEN_LANDS: 'land'}[which]
        return [o for o in context.state.permanents_controlled_by(owner.id) if _matches_permanent_type(o, what)
                and not (which == SET_NONTOKEN_LANDS and o.is_token)]
    if which == SET_GRAVEYARD_CREATURES:
        return [o for o in owner.graveyard if o.is_creature]
    # SET_EXILED_THIS_WAY: the cards the preceding instruction moved to exile and that are still there (RULE 400.7)
    return [o for o in context.exiled_objects if o.zone == Zone.EXILE]


def _start_pool(rules, choice):
    """Begin the next pool of ``choice['queue']`` (RULE 101.4: one decision at a time, in order)."""
    queue = list(choice['queue'])
    while queue and not queue[0]['card_ids']:
        queue.pop(0)  # nothing to separate: no decision, nothing happens to that player's objects
    if not queue:
        _finish(rules, choice)
        return
    pool = queue.pop(0)
    choice = {**choice, 'queue': queue, 'owner_id': pool['owner_id'], 'card_ids': pool['card_ids'],
              'first_ids': [], 'opponent_id': None}
    if ROLE_OPPONENT not in (choice['separator'], choice['chooser']):
        _seat(rules, choice)
        return
    opponents = [p for p in rules.state.living_players_apnap() if p.id != pool['owner_id']]
    if not opponents:
        _start_pool(rules, {**choice, 'card_ids': [], 'queue': queue})  # nobody can separate or choose: skip it
    elif len(opponents) == 1:
        _seat(rules, {**choice, 'opponent_id': opponents[0].id})
    else:
        # "one of their opponents of their choice": the pool's owner names the opponent (Bend or Break, Death or Glory).
        rules.open_choice({**choice, 'kind': 'choose_pile_divider', 'player_id': pool['owner_id'],
            'optional': False, 'prompt': 'Wähle den Gegner für die Stapel',
            'options': [{'id': p.id, 'label': p.name} for p in opponents]})


def _seat(rules, choice):
    """Seat the separator and the chooser of one object pool by role, then ask the separator (RULE 101.4)."""
    seats = {ROLE_YOU: choice['controller_id'], ROLE_OWNER: choice['owner_id'], ROLE_OPPONENT: choice.get('opponent_id')}
    _split(rules, {**choice, 'chooser_id': seats[choice['chooser']]}, seats[choice['separator']])


def _pool_done(rules, choice, chosen_ids, other_ids):
    """Record the chosen and the other pile of one pool, then go on to the next pool or carry out every fate."""
    _start_pool(rules, {**choice, 'chosen_ids': [*choice['chosen_ids'], *chosen_ids],
                        'other_ids': [*choice['other_ids'], *other_ids]})


def _finish(rules, choice):
    by_id = lambda ids: [o for o in (rules.state.find_object(i) for i in ids) if o is not None]
    with rules.state.simultaneous():
        _apply_fate(rules, by_id(choice['chosen_ids']), choice['chosen_fate'], choice)
        _apply_fate(rules, by_id(choice['other_ids']), choice['other_fate'], choice)
    if choice['chosen_fate'] == FATE_PLAY_FREE:
        # RULE 608.2g: the offer follows the pile choice, once nothing else of this instruction is pending; any number of
        # the pile's lands and spells, one at a time (RULE 305.2 counts a land played this way as the land drop).
        pile = [o for o in by_id(choice['chosen_ids']) if o.zone == Zone.EXILE]
        rules._request_resolution_play(rules.state.player_by_id(choice['controller_id']), pile, repeat=True, free=True)


class SeparatePilesEffect(GameEffect):
    """RULE 700.3 / 101.4 / 608.2c: separate a set of objects in a public zone into two piles, one player chooses a pile,
    and each pile meets its printed fate (Do or Die, Liliana of the Veil's -6, Make an Example, Death or Glory, Bend or
    Break, Boneyard Parley, Split the Spoils).

    The choice flow is `reveal_split_piles`'s (one object per answer for the first pile, then the chooser's pick), seated by
    role: ``separator`` and ``chooser`` are ``you`` (the controller), ``owner`` (whose objects they are) or ``opponent`` (an
    opponent of that owner, named by the owner when there are several). ``owners`` is whose objects: the RULE 115 target
    player, each opponent, each player, or the controller. ``set`` names the objects; a pool with none is skipped. Fates
    apply once every pool has been chosen, the chosen piles' first.
    """

    def __init__(self, set=SET_CREATURES, owners=OWNERS_YOU, separator=ROLE_YOU, chooser=ROLE_OWNER,
                 chosen_fate=FATE_DESTROY, other_fate=None, source=None):
        super().__init__(source)
        self.set = set
        self.owners = owners
        self.separator = separator
        self.chooser = chooser
        self.chosen_fate = chosen_fate
        self.other_fate = other_fate
        if owners == OWNERS_TARGET_PLAYER:
            self.target_spec = TargetSpec(kind='player')

    def _owners(self, context, controller, targets):
        state = context.state
        if self.owners == OWNERS_TARGET_PLAYER:
            target = targets[0] if targets else None
            return [target] if target is not None and not target.has_lost else []  # RULE 608.2b
        if self.owners == OWNERS_EACH_OPPONENT:
            return [p for p in state.living_players_apnap() if p.id != controller.id]
        if self.owners == OWNERS_EACH_PLAYER:
            return state.living_players_apnap()
        return [controller]

    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        queue = [{'owner_id': owner.id,
                  'card_ids': [o.instance_id for o in _object_pool(context, controller, owner, self.set)]}
                 for owner in self._owners(context, controller, targets)]
        choice = {'pool': POOL_OBJECTS, 'controller_id': controller.id, 'queue': queue,
                  'source_id': getattr(self.source, 'instance_id', None), 'divider': None,
                  'separator': self.separator, 'chooser': self.chooser, 'chosen_fate': self.chosen_fate,
                  'other_fate': self.other_fate, 'chosen_ids': [], 'other_ids': [], 'face_down': False}
        _start_pool(context.engine, choice)


EffectRegistry.register('reveal_split_piles', lambda p: RevealSplitPilesEffect(
    count=p.get('count', 1), count_selector=p.get('count_selector'), reveal=p.get('reveal', True),
    divider=p.get('divider', DIVIDER_OPPONENT), face_down=p.get('face_down', False), opponent=p.get('opponent'),
    fate=p.get('fate')))
EffectRegistry.register('separate_piles', lambda p: SeparatePilesEffect(
    set=p.get('set', SET_CREATURES), owners=p.get('owners', OWNERS_YOU), separator=p.get('separator', ROLE_YOU),
    chooser=p.get('chooser', ROLE_OWNER), chosen_fate=p.get('chosen_fate', FATE_DESTROY), other_fate=p.get('other_fate')))
