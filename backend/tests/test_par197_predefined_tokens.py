"""PAR-197: native Lander/Spawn abilities survive token creation and binding."""

from unittest.mock import patch

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body, segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.models.game.events import GameEvent, EventType
from mtg_analyzer.services.token_database import default_token_database

SPAWN = 'create a 0/1 colorless eldrazi spawn creature token with "sacrifice ~: add {c}."'


def _game():
    engine = GameEngine.new_game([('p1', 'A', []), ('p2', 'B', [])], starting_hand=0)
    engine.state.current_step = 'main1'
    return engine, engine.state.players[0]


def _permanent(engine, name, oracle, type_line='Creature — Eldrazi Drone'):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=oracle,
                is_creature='Creature' in type_line, power=2, toughness=2)
    assert parse_oracle(card).modeled
    obj = GameObject(card, owner_id='p1', zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id))
    return obj


def _tokens(engine, name):
    return [o for o in engine.state.battlefield if o.name == name]


def _resolve(engine):
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()


def test_named_lander_definition_and_parser():
    spec, = match_clause('create a lander token')
    assert spec.type == 'create_token' and spec.params == {'count': 1, 'token_name': 'Lander'}
    token = default_token_database().get_token('Lander')
    assert token.is_token and token.is_artifact and not token.is_creature
    assert token.type_line == 'Token Artifact — Lander'
    assert not token.color_identity and parse_oracle(token).modeled


@pytest.mark.parametrize('text', [
    SPAWN,
    'create a 0/1 colorless eldrazi spawn creature token. it has "sacrifice ~: add {c}."',
    'create 2 0/1 colorless eldrazi spawn creature tokens. they have "sacrifice ~: add {c}."',
    'create 2 0/1 colorless eldrazi spawn creature tokens. those tokens have "sacrifice ~: add {c}."',
])
def test_quoted_mana_ability_preserved(text):
    spec, = parse_effect_body(text)
    assert spec.type == 'create_token'
    assert 'sacrifice ~: Add {C}.' in spec.params['oracle_text']
    assert spec.params['subtypes'] == ['Eldrazi', 'Spawn']
    assert spec.params['colors'] == []


@pytest.mark.parametrize('ability', [
    'sacrifice ~: frobnicate the moon.',
    'sacrifice ~: add {c}. frobnicate the moon.',
    'sacrifice an imaginary thing: add {c}.',
    'devoid',  # Claimed recognition without a spec is not a native mana ability.
])
def test_unknown_or_non_ability_quote_stays_unclaimed(ability):
    assert match_clause(SPAWN.replace('sacrifice ~: add {c}.', ability)) is None
    assert parse_effect_body('create 2 0/1 colorless eldrazi spawn creature tokens. '
                             f'they have "{ability}"') is None


def test_mana_segment_explicitly_identifies_its_engine_binding_path():
    segment = segment_line('sacrifice ~: add {c}', allow_spell_effect=False, provenance=ParserProvenance())
    assert segment.claimed and segment.spec is None and segment.mana_ability
    assert not segment_line('devoid', allow_spell_effect=False, provenance=ParserProvenance()).mana_ability


def test_chittering_dispatcher_death_makes_spawn_which_sacrifices_immediately_for_colorless():
    engine, player = _game()
    source = _permanent(engine, 'Chittering Dispatcher',
                        'Devoid\nMyriad\nWhen this creature leaves the battlefield, '
                        'create a 0/1 colorless Eldrazi Spawn creature token with '
                        '"Sacrifice this token: Add {C}."')
    engine.rules.put_into_graveyard(source)
    _resolve(engine)
    spawn, = _tokens(engine, 'Eldrazi Spawn')
    engine.recompute_continuous_effects()
    assert spawn.is_creature and not spawn.card.is_artifact
    assert spawn.card.type_line == 'Token Creature — Eldrazi Spawn'
    assert spawn.power == 0 and spawn.toughness == 1 and not spawn.card.color_identity
    assert spawn.summoning_sick  # RULE 302.6 only restricts tap/untap costs.
    assert len(mana_abilities_for(spawn, state=engine.state)) == 1
    assert engine.tap_for_mana(player, spawn) == {'C': 1}
    assert spawn not in engine.state.battlefield
    assert player.mana_pool.total() == 1
    assert not engine.state.stack  # RULE 605.3b: resolves immediately.


def test_propagator_drone_activated_ability_creates_functional_spawn():
    engine, player = _game()
    drone = _permanent(engine, 'Propagator Drone',
                       'Devoid\nCreature tokens you control have evolve.\n'
                       '{3}{G}: Create a 0/1 colorless Eldrazi Spawn creature token with '
                       '"Sacrifice this token: Add {C}."')
    player.mana_pool.add_many({'G': 1, 'C': 3})
    engine.activate_ability(player, drone, 0)
    _resolve(engine)
    spawn, = _tokens(engine, 'Eldrazi Spawn')
    assert player.mana_pool.total() == 0
    engine.tap_for_mana(player, spawn)
    assert player.mana_pool.total() == 1


def test_biomechan_lander_pays_two_taps_sacrifices_searches_basic_tapped_and_shuffles():
    engine, player = _game()
    _permanent(engine, 'Biomechan Engineer',
               'When this creature enters, create a Lander token.\n'
               '{8}: Draw two cards and create a 2/2 colorless Robot artifact creature token.')
    _resolve(engine)
    lander, = _tokens(engine, 'Lander')
    basic = GameObject(Card(id='forest', name='Forest', type_line='Basic Land — Forest', is_land=True),
                       owner_id='p1', zone=Zone.LIBRARY)
    nonbasic = GameObject(Card(id='nonbasic', name='Nonbasic', type_line='Land', is_land=True),
                          owner_id='p1', zone=Zone.LIBRARY)
    player.library.extend([nonbasic, basic])
    with pytest.raises(ValueError):
        engine.activate_ability(player, lander, 0)
    assert lander in engine.state.battlefield
    player.mana_pool.add_many({'C': 2})
    lander.tapped = True
    with pytest.raises(ValueError):
        engine.activate_ability(player, lander, 0)
    lander.tapped = False
    with patch.object(engine.rules, 'shuffle_library', wraps=engine.rules.shuffle_library) as shuffle:
        engine.activate_ability(player, lander, 0)
        assert lander not in engine.state.battlefield
        assert player.mana_pool.total() == 0
        engine.resolve_until_stable()
        choice = engine.state.pending_choice
        assert {o['label'] for o in choice['options'] if 'instance_id' in o} == {'Forest'}
        engine.resolve_pending_choice(next(o['id'] for o in choice['options'] if o.get('label') == 'Forest'))
        engine.resolve_until_stable()
        shuffle.assert_called_once_with(player)
    assert basic.zone == Zone.BATTLEFIELD and basic.tapped
    assert nonbasic.zone == Zone.LIBRARY


@pytest.mark.parametrize('name', ['Pawn of Ulamog', 'Awakening Zone'])
def test_catalogue_spawn_creators_preserve_native_mana_ability(name):
    engine, player = _game()
    # Catalogue lookup is selected by name, independently of parser fallback.
    obj = GameObject(Card(id=name, name=name, type_line='Enchantment'), owner_id='p1', zone=Zone.BATTLEFIELD)
    from mtg_analyzer.game.card_registry import specs_for
    effects = [effect for spec in specs_for(obj.card) for effect in spec.effects if effect.type == 'create_token']
    assert len(effects) == 1
    for effect in build_effects(effects, source=obj):
        effect.apply(GameContext(engine.state, engine.rules))
    spawn, = _tokens(engine, 'Eldrazi Spawn')
    engine.tap_for_mana(player, spawn)
    assert player.mana_pool.total() == 1


@pytest.mark.parametrize('body,count', [
    (SPAWN, 1),
    ('create a 0/1 colorless eldrazi spawn creature token. it has "sacrifice ~: add {c}."', 1),
    ('create 2 0/1 colorless eldrazi spawn creature tokens. they have "sacrifice ~: add {c}."', 2),
])
def test_each_quoted_creation_shape_binds_real_mana_ability(body, count):
    engine, player = _game()
    for effect in build_effects(parse_effect_body(body)):
        effect.apply(GameContext(engine.state, engine.rules))
    spawns = _tokens(engine, 'Eldrazi Spawn')
    assert len(spawns) == count
    for spawn in spawns:
        engine.tap_for_mana(player, spawn)
    assert player.mana_pool.total() == count


def test_quoted_fixed_mana_with_life_cost_charges_the_full_cost():
    engine, player = _game()
    body = SPAWN.replace('sacrifice ~: add {c}.', 'pay 3 life: add {c}.')
    for effect in build_effects(parse_effect_body(body)):
        effect.apply(GameContext(engine.state, engine.rules))
    spawn, = _tokens(engine, 'Eldrazi Spawn')
    life = player.life
    engine.tap_for_mana(player, spawn)
    assert player.life == life - 3
    assert player.mana_pool.total() == 1 and spawn in engine.state.battlefield


@pytest.mark.parametrize('oracle', [
    'Create a 1/1 green Wolf creature token. It has "This token gets +1/+1 for each card named Sound the Call in each graveyard."',
    'Create a 1/1 green Wolf creature token with "This token gets +1/+1 for each card named Sound the Call in each graveyard."',
])
def test_folded_creating_card_name_does_not_rebind_as_token_name(oracle):
    card = Card(id='Sound the Call', name='Sound the Call', type_line='Sorcery', is_sorcery=True, oracle_text=oracle)
    assert not parse_oracle(card).modeled


def test_quoted_monk_tap_mana_keeps_summoning_sickness_and_native_green_production():
    engine, player = _game()
    specs = parse_effect_body('create a 1/1 green human monk creature token with "{t}: add {g}."')
    for effect in build_effects(specs):
        effect.apply(GameContext(engine.state, engine.rules))
    monk, = _tokens(engine, 'Human Monk')
    assert monk.summoning_sick
    with pytest.raises(ValueError):
        engine.tap_for_mana(player, monk)
    monk.summoning_sick = False
    assert engine.tap_for_mana(player, monk) == {'G': 1}
    assert monk.tapped and monk in engine.state.battlefield
