"""Complete library selections preserve named qualities, choice pools and order."""
import pytest
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

DATA = {'Avarax': {'back_keywords': [],
            'back_name': '',
            'back_oracle_text': '',
            'back_power': None,
            'back_toughness': None,
            'back_type_line': '',
            'id': 'd895ddf9-7d94-411c-ad2e-90d47e51810d',
            'is_creature': True,
            'layout': 'normal',
            'name': 'Avarax',
            'oracle_text': 'Haste\n'
                           'When this creature enters, you may search your library for a card named Avarax, '
                           'reveal it, put it into your hand, then shuffle.\n'
                           '{1}{R}: This creature gets +1/+0 until end of turn.',
            'power': 3,
            'toughness': 3,
            'type_line': 'Creature — Beast'},
 'Court Hussar': {'back_keywords': [],
                  'back_name': '',
                  'back_oracle_text': '',
                  'back_power': None,
                  'back_toughness': None,
                  'back_type_line': '',
                  'id': 'f3843e98-192c-44a2-be54-9ba79e51657c',
                  'is_creature': True,
                  'layout': 'normal',
                  'name': 'Court Hussar',
                  'oracle_text': 'Vigilance\n'
                                 'When this creature enters, look at the top three cards of your library, '
                                 'then put one of them into your hand and the rest on the bottom of your '
                                 'library in any order.\n'
                                 'When this creature enters, sacrifice it unless {W} was spent to cast it.',
                  'power': 1,
                  'toughness': 3,
                  'type_line': 'Creature — Vedalken Knight'},
 'Embermage Goblin': {'back_keywords': [],
                      'back_name': '',
                      'back_oracle_text': '',
                      'back_power': None,
                      'back_toughness': None,
                      'back_type_line': '',
                      'id': 'f50f60a8-e99a-4891-b474-a21abee38970',
                      'is_creature': True,
                      'layout': 'normal',
                      'name': 'Embermage Goblin',
                      'oracle_text': 'When this creature enters, you may search your library for a card '
                                     'named Embermage Goblin, reveal it, put it into your hand, then '
                                     'shuffle.\n'
                                     '{T}: This creature deals 1 damage to any target.',
                      'power': 1,
                      'toughness': 1,
                      'type_line': 'Creature — Goblin Wizard'},
 'Growth-Chamber Guardian': {'back_keywords': [],
                             'back_name': '',
                             'back_oracle_text': '',
                             'back_power': None,
                             'back_toughness': None,
                             'back_type_line': '',
                             'id': '0f97cdf4-231d-4bd0-af5e-bcb64ce1556c',
                             'is_creature': True,
                             'layout': 'normal',
                             'name': 'Growth-Chamber Guardian',
                             'oracle_text': '{2}{G}: Adapt 2. (If this creature has no +1/+1 counters on it, '
                                            'put two +1/+1 counters on it.)\n'
                                            'Whenever one or more +1/+1 counters are put on this creature, '
                                            'you may search your library for a card named Growth-Chamber '
                                            'Guardian, reveal it, put it into your hand, then shuffle.',
                             'power': 2,
                             'toughness': 2,
                             'type_line': 'Creature — Elf Crab Warrior'},
 'Jar of Eyeballs': {'back_keywords': [],
                     'back_name': '',
                     'back_oracle_text': '',
                     'back_power': None,
                     'back_toughness': None,
                     'back_type_line': '',
                     'id': '72da56bd-dd1c-4b3c-a655-afa31e9adca0',
                     'is_creature': False,
                     'layout': 'normal',
                     'name': 'Jar of Eyeballs',
                     'oracle_text': 'Whenever a creature you control dies, put two eyeball counters on this '
                                    'artifact.\n'
                                    '{3}, {T}, Remove all eyeball counters from this artifact: Look at the '
                                    'top X cards of your library, where X is the number of eyeball counters '
                                    'removed this way. Put one of them into your hand and the rest on the '
                                    'bottom of your library in any order.',
                     'power': None,
                     'toughness': None,
                     'type_line': 'Artifact'},
 'Soulcipher Board // Cipherbound Spirit': {'back_keywords': ['Flying'],
                                            'back_name': 'Cipherbound Spirit',
                                            'back_oracle_text': 'Flying\n'
                                                                'This creature can block only creatures with '
                                                                'flying.\n'
                                                                '{3}{U}: Draw two cards, then discard a '
                                                                'card.',
                                            'back_power': 3,
                                            'back_toughness': 2,
                                            'back_type_line': 'Creature — Spirit',
                                            'id': '73e7ed48-8f7b-4bdf-bade-a09597ceafcd',
                                            'is_creature': False,
                                            'layout': 'transform',
                                            'name': 'Soulcipher Board // Cipherbound Spirit',
                                            'oracle_text': 'This artifact enters with three omen counters on '
                                                           'it.\n'
                                                           '{1}{U}, {T}: Look at the top two cards of your '
                                                           'library. Put one of them into your graveyard.\n'
                                                           'Whenever a creature card is put into your '
                                                           'graveyard from anywhere, remove an omen counter '
                                                           'from this artifact. Then if it has no omen '
                                                           'counters on it, transform it.',
                                            'power': None,
                                            'toughness': None,
                                            'type_line': 'Artifact'}}


def _engine():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state.players[0]


def _stock(player, names):
    objects = [GameObject(Card(id=n, name=n, type_line="Creature — Bear", is_creature=True,
                               power=2, toughness=2), owner_id=player.id, zone=Zone.LIBRARY) for n in names]
    player.library.extend(reversed(objects))
    return objects


def _board(engine, name):
    obj = GameObject(Card(**DATA[name]), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
                                      controller_id=obj.controller_id, object_types=sorted(obj.type_words)))
    return obj


def _resolve(engine):
    engine.resolve_until_stable()
    while engine.state.pending_choice and any(o['id'] == 'do' for o in engine.state.pending_choice['options']):
        engine.resolve_pending_choice('do')
        engine.resolve_until_stable()


@pytest.mark.parametrize('name', DATA)
def test_complete_real_card_parses(name):
    card = Card(**DATA[name])
    assert parse_oracle(card).modeled
    if card.back_name:
        assert parse_oracle(card.back_face()).modeled


@pytest.mark.parametrize('name', ['Avarax', 'Embermage Goblin', 'Growth-Chamber Guardian'])
def test_named_reveal_search_sequence(name):
    engine, player = _engine()
    wanted, other = _stock(player, [name, 'Wrong name'])
    source = _board(engine, name)
    if name == 'Growth-Chamber Guardian':
        engine.rules.context.add_counters(source, 2, '+1/+1', source=source)
    _resolve(engine)
    choice = engine.state.pending_choice
    assert choice and choice['kind'] == 'search'
    assert choice['criteria']['name'] == name
    offered = {str(o.get('instance_id')) for o in choice['options']}
    assert str(wanted.instance_id) in offered
    assert str(other.instance_id) not in offered
    engine.resolve_pending_choice(str(wanted.instance_id))
    assert wanted in player.hand and other in player.library
    events = list(engine.state.events_this_turn())
    assert any(e.type == EventType.REVEAL and e.get('instance_id') == wanted.instance_id for e in events)
    assert any(e.type == EventType.SHUFFLE for e in events)


def test_court_hussar_complete_trigger_and_chosen_bottom_order_clone():
    engine, player = _engine()
    a, b, c, untouched = _stock(player, ['A', 'B', 'C', 'Untouched'])
    source = _board(engine, 'Court Hussar')
    _resolve(engine)
    assert source.zone == Zone.GRAVEYARD  # No white mana was spent to cast it.
    assert engine.state.pending_choice['kind'] == 'look_top_select'
    invalid = GameEngine(engine.state.clone())
    with pytest.raises(ValueError):
        invalid.resolve_pending_choice(str(untouched.instance_id))
    engine.resolve_pending_choice(str(b.instance_id))
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(c.instance_id))
    clone.resolve_pending_choice(str(a.instance_id))
    cp = clone.state.player_by_id('p1')
    assert [o.name for o in cp.hand] == ['B']
    assert [o.name for o in cp.library] == ['A', 'C', 'Untouched']
    assert not player.hand and engine.state.pending_choice['phase'] == 'order'
    engine.resolve_pending_choice(str(a.instance_id))
    engine.resolve_pending_choice(str(c.instance_id))
    assert [o.name for o in player.library] == ['C', 'A', 'Untouched']


def test_soulcipher_pick_graveyard_triggers_transform_and_back_ability():
    engine, player = _engine()
    chosen, untouched, bottom = _stock(player, ['Creature', 'Untouched', 'Bottom'])
    board = _board(engine, 'Soulcipher Board // Cipherbound Spirit')
    _resolve(engine)
    board.counters['omen'] = 1
    player.mana_pool.add_many({'U': 1, 'C': 1})
    engine.activate_ability(player, board, ability_index=0)
    _resolve(engine)
    assert engine.state.pending_choice['kind'] == 'choose_objects'
    engine.resolve_pending_choice(str(chosen.instance_id))
    _resolve(engine)
    assert chosen in player.graveyard
    assert [o.name for o in player.library] == ['Bottom', 'Untouched']
    assert board.transformed and board.name == 'Cipherbound Spirit'
    player.mana_pool.add_many({'U': 1, 'C': 3})
    engine.activate_ability(player, board, ability_index=0)
    _resolve(engine)
    assert {o.name for o in player.hand} == {'Bottom', 'Untouched'}
    assert engine.state.pending_choice['kind'] == 'choose_objects'
    assert engine.state.pending_choice['action'] == 'discard'
    engine.resolve_pending_choice(str(untouched.instance_id))
    assert untouched in player.graveyard and bottom in player.hand


def test_jar_removed_counter_count_survives_source_mutation_and_order_choice_clone():
    engine, player = _engine()
    a, b, c, bottom = _stock(player, ['A', 'B', 'C', 'Bottom'])
    jar = _board(engine, 'Jar of Eyeballs')
    jar.counters['eyeball'] = 3
    player.mana_pool.add_many({'C': 3})
    engine.activate_ability(player, jar, ability_index=0)
    assert not jar.counters.get('eyeball')
    jar.counters_removed_as_cost = 1  # A subsequent activation cannot rewrite this payment.
    _resolve(engine)
    assert set(engine.state.pending_choice['remaining']) == {a.instance_id, b.instance_id, c.instance_id}
    engine.resolve_pending_choice(str(b.instance_id))
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(c.instance_id))
    clone.resolve_pending_choice(str(a.instance_id))
    assert [o.name for o in clone.state.player_by_id('p1').hand] == ['B']
    assert [o.name for o in clone.state.player_by_id('p1').library] == ['A', 'C', 'Bottom']
    assert not player.hand


def test_removed_counter_measure_requires_matching_paid_cost():
    text = ('{T}: Look at the top X cards of your library, where X is the number of eyeball counters removed this way. '
            'Put one of them into your hand and the rest on the bottom of your library in any order.')
    assert not parse_oracle(Card(id='bad', name='Bad', type_line='Artifact', oracle_text=text)).modeled
    assert not parse_oracle(Card(id='bad2', name='Bad2', type_line='Artifact',
                                oracle_text=text.replace('{T}:', '{T}, Remove all omen counters from this artifact:'))).modeled
    assert parse_effect_body('look at the top 3 cards of your library, then put 1 of them into your hand and exile the rest') is None


@pytest.mark.parametrize('name', ['Avarax', 'Embermage Goblin', 'Growth-Chamber Guardian'])
def test_named_search_can_decline_after_choosing_to_search(name):
    engine, player = _engine()
    wanted, = _stock(player, [name])
    source = _board(engine, name)
    if name == 'Growth-Chamber Guardian':
        engine.rules.context.add_counters(source, 1, '+1/+1', source=source)
    _resolve(engine)
    engine.resolve_pending_choice('decline')
    assert wanted in player.library and not player.hand
    assert any(e.type == EventType.SHUFFLE for e in engine.state.events_this_turn())
    assert not any(e.type == EventType.REVEAL for e in engine.state.events_this_turn())


@pytest.mark.parametrize('name', ['Court Hussar', 'Jar of Eyeballs'])
@pytest.mark.parametrize('size', [0, 1, 2])
def test_look_pool_smaller_than_requested_keeps_exact_remaining_count(name, size):
    engine, player = _engine()
    objects = _stock(player, [f'Card {i}' for i in range(size)])
    source = _board(engine, name)
    if name == 'Jar of Eyeballs':
        source.counters['eyeball'] = 4
        player.mana_pool.add_many({'C': 3})
        engine.activate_ability(player, source, ability_index=0)
    _resolve(engine)
    if size == 0:
        assert engine.state.pending_choice is None and not player.hand
    else:
        assert len(engine.state.pending_choice['remaining']) == size
        engine.resolve_pending_choice(str(objects[0].instance_id))
        assert engine.state.pending_choice is None
        assert player.hand == objects[:1] and player.library == list(reversed(objects[1:]))


def test_jar_zero_removed_counters_does_not_inspect_or_take_a_card():
    engine, player = _engine()
    objects = _stock(player, ['A', 'B'])
    source = _board(engine, 'Jar of Eyeballs')
    player.mana_pool.add_many({'C': 3})
    engine.activate_ability(player, source, ability_index=0)
    _resolve(engine)
    assert source.tapped and not engine.state.pending_choice
    assert not player.hand and player.library == list(reversed(objects))


def test_two_jar_activations_keep_independent_counter_payments():
    engine, player = _engine()
    a, b, c, d, e = _stock(player, ['A', 'B', 'C', 'D', 'E'])
    jar = _board(engine, 'Jar of Eyeballs')
    player.mana_pool.add_many({'C': 6})
    jar.counters['eyeball'] = 3
    engine.activate_ability(player, jar, ability_index=0)
    jar.tapped = False
    jar.counters['eyeball'] = 1
    engine.activate_ability(player, jar, ability_index=0)
    _resolve(engine)
    assert engine.state.pending_choice['remaining'] == [a.instance_id]
    engine.resolve_pending_choice(str(a.instance_id))
    assert engine.state.pending_choice['remaining'] == [b.instance_id, c.instance_id, d.instance_id]
    engine.resolve_pending_choice(str(c.instance_id))
    engine.resolve_pending_choice(str(d.instance_id))
    engine.resolve_pending_choice(str(b.instance_id))
    assert [o.name for o in player.hand] == ['A', 'C']
    assert [o.name for o in player.library] == ['B', 'D', 'E']


@pytest.mark.parametrize("wanted_name", ["Festering Newt", "Bubbling Cauldron"])
def test_named_alternatives_offer_each_name_and_execute_selected_search(wanted_name):
    engine, player = _engine()
    newt, cauldron, wrong = _stock(player, ["Festering Newt", "Bubbling Cauldron", "Wrong"])
    witch = GameObject(Card(id="witch", name="Bogbrew Witch", type_line="Creature — Human Wizard",
        is_creature=True, power=1, toughness=3, oracle_text=(
        "{2}, {T}: Search your library for a card named Festering Newt or Bubbling Cauldron, "
        "put it onto the battlefield tapped, then shuffle.")), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(witch)
    engine.state.add_to_battlefield(witch)
    witch.summoning_sick = False
    player.mana_pool.add_many({"C": 2})
    engine.activate_ability(player, witch)
    _resolve(engine)
    choice = engine.state.pending_choice
    offered = {str(option["instance_id"]) for option in choice["options"] if "instance_id" in option}
    assert offered == {str(newt.instance_id), str(cauldron.instance_id)}
    wanted = next(obj for obj in (newt, cauldron) if obj.name == wanted_name)
    engine.resolve_pending_choice(str(wanted.instance_id))
    assert wanted.zone == Zone.BATTLEFIELD and wanted.tapped
    assert wrong in player.library
    assert any(event.type == EventType.SHUFFLE for event in engine.state.events_this_turn())
