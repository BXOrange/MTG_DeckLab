"""MEC-128: one graveyard per occurrence of target, across announcement paths."""
import pytest
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _hand
from test_par157_target_budgets import _dead

BODY = 'Exile up to three target cards from a single graveyard.'


def _spell(eng, text=BODY):
    return _hand(eng, Card(id='decompose', name='Decompose', type_line='Sorcery',
        is_sorcery=True, oracle_text=text))


@pytest.mark.parametrize('count', [0, 1, 2, 3])
@pytest.mark.parametrize('kind', ['spell', 'activation'])
def test_zero_through_max_and_cross_graveyard_rejection(kind, count):
    eng = _engine()
    cards = [_dead(eng, f'Own {i}', 1) for i in range(3)]
    other = _dead(eng, 'Other', 1, 'p2')
    player = eng.state.player_by_id('p1')
    if kind == 'spell':
        source = _spell(eng)
        act = lambda targets: eng.cast_spell(player, source, targets=targets)
    else:
        source = _bf(eng, Card(id='beetles', name='Carrion Beetles', type_line='Artifact',
            oracle_text='{1}, {T}: ' + BODY))
        player.mana_pool.add('C', 1)
        act = lambda targets: eng.activate_ability(player, source, 0, targets=targets)
        req = eng._ability_target_requirements(player, source.activated_abilities[0], source)[0]
        assert req['same_graveyard'] and {o['graveyard_owner_id'] for o in req['options']} == {'p1', 'p2'}
    with pytest.raises(ValueError, match='limit'):
        act([cards[0], other])
    assert not source.tapped
    act(cards[:count])
    eng.resolve_until_stable()
    assert all(c.zone == (Zone.EXILE if i < count else Zone.GRAVEYARD) for i, c in enumerate(cards))
    assert other.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('all_illegal', [False, True])
def test_resolution_keeps_legal_members_and_rejects_new_zone_visits(all_illegal):
    eng = _engine()
    cards = [_dead(eng, f'Visit {i}', 1, 'p2') for i in range(2)]
    spell = _spell(eng)
    eng.cast_spell(eng.state.player_by_id('p1'), spell, targets=cards)
    for obj in cards if all_illegal else cards[:1]:
        eng.rules.return_from_graveyard(obj, 'hand')
        eng.rules.put_into_graveyard(obj)
    eng.resolve_until_stable()
    assert cards[0].zone == Zone.GRAVEYARD
    assert cards[1].zone == (Zone.GRAVEYARD if all_illegal else Zone.EXILE)


@pytest.mark.parametrize('count', [0, 1, 2])
def test_trigger_offers_one_graveyard_and_clone_retains_selection(count):
    eng = _engine()
    cards = [_dead(eng, f'Trigger {i}', 1, 'p2') for i in range(2)]
    other = _dead(eng, 'Unrelated', 1)
    source = _bf(eng, Card(id='tracker', name='Griffnaut Tracker', type_line='Creature — Human',
        is_creature=True, power=2, toughness=2,
        oracle_text='When this creature enters, exile up to two target cards from a single graveyard.'))
    from mtg_analyzer.models.game.events import GameEvent, EventType
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id))
    eng.resolve_until_stable()
    if count:
        eng.resolve_pending_choice(str(cards[0].instance_id))
        offered = {o['id'] for o in eng.state.pending_choice['options']}
        assert str(other.instance_id) not in offered and str(cards[1].instance_id) in offered
        from mtg_analyzer.game.game_engine import GameEngine
        eng = GameEngine(eng.state.clone())
        if count == 2:
            eng.resolve_pending_choice(str(cards[1].instance_id))
    if eng.state.pending_choice:
        eng.resolve_pending_choice('stop')
    eng.resolve_until_stable()
    for i, obj in enumerate(cards):
        assert eng.state.find_object(obj.instance_id).zone == (Zone.EXILE if i < count else Zone.GRAVEYARD)
    assert eng.state.find_object(other.instance_id).zone == Zone.GRAVEYARD


def test_plural_graveyards_still_accepts_mixed_owners():
    eng = _engine()
    cards = [_dead(eng, 'First', 1), _dead(eng, 'Second', 1, 'p2')]
    spell = _spell(eng, 'Exile up to three target cards from graveyards.')
    eng.cast_spell(eng.state.player_by_id('p1'), spell, targets=cards)
    eng.resolve_until_stable()
    assert all(c.zone == Zone.EXILE for c in cards)


@pytest.mark.parametrize('text', [
    'exile up to x target cards from a single graveyard',
    'exile up to 3 target cards from a single graveyard unless their owner pays {1}',
])
def test_unsupported_extensions_fail_closed(text):
    assert parse_effect_body(text) is None


def test_real_spell_binding():
    eng = _engine()
    spell = _spell(eng)
    assert parse_oracle(spell.card).modeled
    assert spell.spell_effects[0].target_spec.same_graveyard


@pytest.mark.full_cache
@pytest.mark.parametrize('name', [
    'Arashin Sunshield', 'Carrion Beetles', 'Cease // Desist', 'Decompose',
    'Digsite Conservator', 'Ebony Charm', 'Famished Ghoul', 'Griffnaut Tracker',
    'Rag Dealer', 'Rapid Decay', 'Scarab Feast', 'Shred Memory',
    'Feral Deathgorger // Dusk Sight', 'Qutrub Forayer',
])
def test_verified_candidate_is_fully_modeled(name):
    from test_par157_back_selections import _cached
    assert parse_oracle(_cached(name)).modeled


def test_excess_and_duplicate_picks_are_rejected_before_payment():
    eng = _engine()
    cards = [_dead(eng, f'Count {i}', 1) for i in range(4)]
    player = eng.state.player_by_id('p1')
    spell = _spell(eng)
    for picks in [cards, [cards[0], cards[0]]]:
        with pytest.raises(ValueError, match='illegal targets'):
            eng.cast_spell(player, spell, targets=picks)
    assert spell.zone == Zone.HAND


def test_copy_changing_targets_preserves_single_graveyard_relation():
    eng = _engine()
    own = [_dead(eng, f'Original {i}', 1) for i in range(2)]
    other = [_dead(eng, f'Copy {i}', 1, 'p2') for i in range(2)]
    original = eng.cast_spell(eng.state.player_by_id('p1'), _spell(eng), targets=own)
    copied = eng.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    choice = eng.state.pending_choice
    eng.rules.resolve_choice(next(o['id'] for o in choice['options'] if o.get('instance_id') == other[0].instance_id))
    options = eng.state.pending_choice['options']
    assert own[1].instance_id not in {o.get('instance_id') for o in options}
    eng.rules.resolve_choice(next(o['id'] for o in options if o.get('instance_id') == other[1].instance_id))
    assert copied.targets == other and original.targets == own
    eng.resolve_until_stable()
    assert all(c.zone == Zone.EXILE for c in own + other)


@pytest.mark.full_cache
@pytest.mark.parametrize('name', ['Decompose', 'Scarab Feast', 'Carrion Beetles', 'Griffnaut Tracker'])
def test_cached_cards_bind_and_execute(name):
    from test_par157_back_selections import _cached
    from mtg_analyzer.models.game.events import GameEvent, EventType
    eng = _engine()
    targets = [_dead(eng, f'Cached victim {i}', 1, 'p2') for i in range(2)]
    card = _cached(name)
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'B': 5, 'C': 10})
    if name in {'Decompose', 'Scarab Feast'}:
        source = _hand(eng, card)
        assert source.spell_effects[0].target_spec.same_graveyard
        eng.cast_spell(player, source, targets=targets)
    elif name == 'Carrion Beetles':
        source = _bf(eng, card)
        assert source.activated_abilities[0].effects[0].target_spec.same_graveyard
        eng.activate_ability(player, source, 0, targets=targets)
    else:
        source = _bf(eng, card)
        eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id))
        eng.resolve_until_stable()
        for obj in targets:
            eng.rules.resolve_choice(str(obj.instance_id))
    eng.resolve_until_stable()
    assert all(obj.zone == Zone.EXILE for obj in targets)


@pytest.mark.parametrize('kind', ['spell', 'activation', 'trigger'])
def test_optional_effect_with_empty_graveyards(kind):
    eng = _engine()
    player = eng.state.player_by_id('p1')
    if kind == 'spell':
        eng.cast_spell(player, _spell(eng), targets=[])
    elif kind == 'activation':
        source = _bf(eng, Card(id='empty activation', name='Empty activation', type_line='Artifact',
            oracle_text='{0}: ' + BODY))
        eng.activate_ability(player, source, 0, targets=[])
    else:
        from mtg_analyzer.models.game.events import GameEvent, EventType
        source = _bf(eng, Card(id='empty trigger', name='Empty trigger', type_line='Enchantment',
            oracle_text='At the beginning of your upkeep, ' + BODY))
        eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.resolve_until_stable()
    assert not eng.state.pending_choice and not eng.state.stack
