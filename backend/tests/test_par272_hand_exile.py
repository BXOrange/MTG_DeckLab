"""PAR-272: private hand choices, draw compensation and taxed owner permission."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.game_session import GameSession
from tests.test_mec118_opponent_choice import _engine, _put, _db_card
from tests.test_par187_hand_disruption import names


NAMES = ['Salt Vampire', 'Zero, Incorporeal Sensate']


def hand(eng, name, pid='p2'):
    return _put(eng, _db_card(name), pid, Zone.HAND)


def enter(eng, name):
    source = hand(eng, name, 'p1')
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({color: 10 for color in 'WUBRGC'})
    eng.cast_spell(player, source)
    eng.resolve_until_stable()
    while eng.state.pending_choice and eng.state.pending_choice['kind'] in {'trigger_target', 'choose_protector'}:
        eng.resolve_pending_choice('p2')
        eng.resolve_until_stable()
    return source


def library(eng, name='Island', pid='p2'):
    obj = hand(eng, name, pid)
    player = eng.state.player_by_id(pid)
    player.hand.remove(obj)
    obj.zone = Zone.LIBRARY
    player.library.append(obj)
    return obj


@pytest.mark.parametrize('name', NAMES + ['Elite Spellbinder', 'Invasion of Gobakhan // Lightshield Array'])
def test_real_family_cards_parse(name):
    card = _db_card(name)
    assert card is not None
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


@pytest.mark.parametrize('name', NAMES)
def test_private_hand_visibility_and_clone_decline(name):
    eng = _engine(3)
    pick = hand(eng, 'Grizzly Bears')
    land = hand(eng, 'Forest')
    enter(eng, name)
    session = GameSession(eng)
    assert names(session.view(perspective='p1')) == {'Grizzly Bears', 'Forest'}
    assert names(session.view(perspective='p2')) == {'Grizzly Bears', 'Forest'}
    assert not names(session.view(perspective='p3'))
    assert not names(session.observer_view())
    choice = eng.state.pending_choice
    assert {o['instance_id'] for o in choice['options'] if 'instance_id' in o} == {pick.instance_id}
    restored = GameEngine(eng.state.clone())
    restored.resolve_pending_choice('decline')
    restored.resolve_until_stable()
    assert restored.state.find_object(pick.instance_id).zone == Zone.HAND
    assert restored.state.find_object(land.instance_id).zone == Zone.HAND
    assert not restored.state.exile_cast_condition


def test_salt_vampire_exiles_chosen_card_then_only_that_player_draws():
    eng = _engine(3)
    pick = hand(eng, 'Grizzly Bears')
    drawn = library(eng)
    source = enter(eng, NAMES[0])
    eng.rules.return_to_hand(source)  # permission/compensation is independent of its source
    eng.resolve_pending_choice(str(pick.instance_id))
    eng.resolve_until_stable()
    assert pick.zone == Zone.EXILE
    assert drawn in eng.state.player_by_id('p2').hand
    assert len(eng.state.player_by_id('p1').hand) == 1
    assert not eng.state.player_by_id('p3').hand
    assert pick.instance_id not in eng.state.exile_cast_condition


@pytest.mark.parametrize('name', NAMES)
@pytest.mark.parametrize('has_hand', [True, False])
def test_no_eligible_card_has_no_exile_compensation_or_permission(name, has_hand):
    eng = _engine(3)
    if has_hand:
        hand(eng, 'Forest')
    drawn = library(eng)
    enter(eng, name)
    if eng.state.pending_choice:
        assert eng.state.pending_choice['kind'] == 'look_hand'
        eng.resolve_pending_choice('decline')
        eng.resolve_until_stable()
    assert drawn in eng.state.player_by_id('p2').library
    assert not eng.state.exile_cast_condition


def exile_with_zero(eng, card_name='Grizzly Bears', source_name=NAMES[1]):
    pick = hand(eng, card_name)
    source = enter(eng, source_name)
    eng.resolve_pending_choice(str(pick.instance_id))
    eng.resolve_until_stable()
    assert pick.zone == Zone.EXILE
    return source, pick


@pytest.mark.parametrize('name', [NAMES[1], 'Elite Spellbinder', 'Invasion of Gobakhan // Lightshield Array'])
def test_owner_casts_from_exile_with_two_extra_generic_mana_after_source_leaves(name):
    eng = _engine(3)
    source, pick = exile_with_zero(eng, source_name=name)
    eng.rules.return_to_hand(source)
    eng.state.active_player_index = 1
    owner = eng.state.player_by_id('p2')
    owner.mana_pool.add('G', 2)
    assert not eng.can_cast(owner, pick)
    owner.mana_pool.add('C', 2)
    assert eng.can_cast(owner, pick)
    assert not eng.can_cast(eng.state.player_by_id('p1'), pick)
    eng.cast_spell(owner, pick)
    eng.resolve_until_stable()
    assert pick in eng.state.battlefield
    assert owner.mana_pool.total() == 0


def test_zero_permission_does_not_return_on_a_later_exile_visit():
    eng = _engine()
    _, pick = exile_with_zero(eng)
    eng.rules.return_to_hand(pick)
    eng.rules.exile(pick)
    eng.state.active_player_index = 1
    owner = eng.state.player_by_id('p2')
    owner.mana_pool.add_many({'G': 10, 'C': 10})
    assert not eng.can_cast(owner, pick)


@pytest.mark.parametrize('name', NAMES)
def test_hand_pick_rejects_departed_and_returned_visit(name):
    eng = _engine(3)
    pick = hand(eng, 'Grizzly Bears')
    enter(eng, name)
    eng.rules.exile(pick)
    eng.rules.return_to_hand(pick)
    with pytest.raises(ValueError):
        eng.resolve_pending_choice(str(pick.instance_id))
    assert pick.zone == Zone.HAND


@pytest.mark.parametrize('text', [
    "look at target opponent's hand. you choose a nonland card from it",
    "look at target opponent's hand. you may exile a nonland card from it",
    "look at target opponent's hand. you may choose a nonland card from it. if you do, that player exiles that card, then draws cards equal to a mystery",
    "look at target opponent's hand. you may exile a nonland card from it. for as long as that card remains exiled, you may play it. a spell cast this way costs {2} more to cast",
])
def test_unsupported_variants_fail_closed(text):
    assert parse_effect_body(text) is None


def test_zero_allows_land_back_face_with_normal_timing_and_land_limit():
    eng = _engine(3)
    _, pick = exile_with_zero(eng, 'Bala Ged Recovery // Bala Ged Sanctuary')
    owner = eng.state.player_by_id('p2')
    assert not eng.can_play_land(owner, pick, face='back')
    eng.state.active_player_index = 1
    assert eng.can_play_land(owner, pick, face='back')
    eng.play_land(owner, pick, face='back')
    assert pick.zone == Zone.BATTLEFIELD and pick.is_land and pick.tapped
    assert owner.mana_pool.total() == 0  # the spell-only tax never prices a land play
    second = hand(eng, 'Forest')
    assert not eng.can_play_land(owner, second)


@pytest.mark.parametrize('name', NAMES)
def test_rewind_and_clone_preserve_private_selection_and_followup(name):
    eng = _engine(3)
    pick = hand(eng, 'Grizzly Bears')
    drawn = library(eng)
    enter(eng, name)
    restored = GameEngine(eng.state.clone())
    session = GameSession(eng)
    session.apply_action({'type': 'choose', 'option_id': str(pick.instance_id)}, actor_id='p1')
    session.rewind()
    assert session.engine.state.find_object(pick.instance_id).zone == Zone.HAND
    assert names(session.view(perspective='p1')) == {'Grizzly Bears'}
    assert not names(session.view(perspective='p3'))
    for engine in (session.engine, restored):
        engine.resolve_pending_choice(str(pick.instance_id))
        engine.resolve_until_stable()
        assert engine.state.find_object(pick.instance_id).zone == Zone.EXILE
        if name == NAMES[0]:
            assert engine.state.find_object(drawn.instance_id).zone == Zone.HAND
        else:
            owner = engine.state.player_by_id('p2')
            engine.state.active_player_index = 1
            owner.mana_pool.add_many({'G': 2, 'C': 2})
            assert engine.can_cast(owner, engine.state.find_object(pick.instance_id))


def test_salt_compensation_waits_for_opponents_draw_replacement():
    eng = _engine(3)
    pick = hand(eng, 'Grizzly Bears')
    library(eng, 'Forest')
    library(eng, 'Island')
    _put(eng, _db_card('Abundance'), 'p2')
    enter(eng, NAMES[0])
    eng.resolve_pending_choice(str(pick.instance_id))
    eng.resolve_until_stable()
    assert pick.zone == Zone.EXILE
    assert eng.state.pending_choice['kind'] == 'optional_draw_dig'
    assert eng.state.pending_choice['player_id'] == 'p2'
    restored = GameEngine(eng.state.clone())
    restored.resolve_pending_choice('decline')
    restored.resolve_until_stable()
    assert restored.state.pending_choice is None
    assert restored.state.player_by_id('p2').hand[-1].name == 'Island'
    assert not restored.state.player_by_id('p1').hand


def test_conditional_draw_uses_shared_printed_count_grammar():
    specs = parse_effect_body("look at target opponent's hand. you may choose a nonland card from it. "
                              "if you do, that player exiles that card, then draws 2 cards")
    assert specs[0].params['then_specs'][0]['params']['effects'][1]['params']['count'] == 2
