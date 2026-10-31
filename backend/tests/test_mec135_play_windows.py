"""MEC-135: exact-card permissions in graveyards and libraries."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature
from test_par167_casting_windows import _instant


def _window(eng, text):
    source = _bf(eng, _creature('Grantor'))
    specs = parse_effect_body(text)
    assert specs
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context)


def _top(eng, land=False, owner='p1'):
    card = Card(id='land', name='Land', type_line='Land', is_land=True) if land else _instant(cost='{0}', mv=0)
    obj = GameObject(card, owner_id=owner, zone=Zone.LIBRARY)
    eng.state.player_by_id(owner).library.append(obj)
    return obj


@pytest.mark.parametrize('producer', ['mill a card', 'reveal the top card of your library'])
@pytest.mark.parametrize('land', [False, True])
def test_window_offers_and_plays_the_actual_card(producer, land):
    eng = _engine()
    player = eng.state.active_player
    obj = _top(eng, land)
    _window(eng, producer + '. you may play that card this turn.')
    assert eng.can_play_land(player, obj) if land else eng.can_cast(player, obj)
    actions = [a for a in eng.legal_actions(player) if a.get('instance_id') == obj.instance_id
               and a['type'] == ('play_land' if land else 'cast_spell')]
    assert len(actions) == 1
    if land:
        eng.play_land(player, obj)
        assert obj.zone == Zone.BATTLEFIELD
    else:
        eng.cast_spell(player, obj)
        eng.resolve_until_stable()
        assert obj.zone == Zone.GRAVEYARD
        assert not eng.can_cast(player, obj)  # cannot recast after a new visit


@pytest.mark.parametrize('producer', ['mill a card', 'reveal the top card of your library'])
def test_window_expiry_holder_and_timing(producer):
    eng = _engine()
    player = eng.state.active_player
    obj = _top(eng)
    _window(eng, producer + '. you may play that card this turn.')
    assert not eng.can_cast(eng.state.player_by_id('p2'), obj)
    eng.state.current_step = 'upkeep'
    # Instant timing is retained, but a land must still wait for main phase.
    assert eng.can_cast(player, obj)
    eng._step_cleanup()
    assert not eng.can_cast(player, obj)


def test_cast_only_mill_window_excludes_lands():
    eng = _engine()
    obj = _top(eng, land=True)
    _window(eng, 'mill a card. you may cast that card this turn.')
    assert not eng.can_play_land(eng.state.active_player, obj)


def test_library_permission_survives_a_change_of_top_card():
    eng = _engine()
    obj = _top(eng)
    _window(eng, 'reveal the top card of your library. you may cast that card this turn.')
    _top(eng, land=True)
    assert eng.can_cast(eng.state.active_player, obj)
    assert any(a.get('instance_id') == obj.instance_id for a in eng.legal_actions(eng.state.active_player))


@pytest.mark.parametrize('text', [
    'mill 2 cards. you may play that card this turn.',
    'reveal the top 2 cards of your library. you may cast that card this turn.',
    'mill a card. you may play that card for as long as it remains exiled.',
    'mill 3 cards. until end of turn, you may cast a spell from among them.',
])
def test_unknown_or_ambiguous_windows_fail_closed(text):
    assert parse_effect_body(text) is None


def test_reveal_cast_without_duration_is_a_resolution_choice():
    eng = _engine()
    obj = _top(eng)
    _window(eng, 'reveal the top card of your library. you may cast that card without paying its mana cost.')
    assert eng.state.pending_choice['kind'] == 'play_during_resolution'
    eng.play_resolution_card(eng.state.active_player, obj)
    eng.resolve_until_stable()
    assert obj.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('name', ['Ark of Hunger', 'Tablet of Discovery'])
@pytest.mark.full_cache
def test_real_mill_cards_bind_and_play(name):
    from test_par157_back_selections import _cached
    from mtg_analyzer.parser.oracle import parse_oracle
    eng = _engine()
    obj = _top(eng)
    card = _cached(name)
    assert parse_oracle(card).modeled
    from test_mec106_gift import _hand
    source = _hand(eng, card)
    for color in 'WUBRGC':
        eng.state.active_player.mana_pool.add(color, 10)
    eng.cast_spell(eng.state.active_player, source)
    eng.resolve_until_stable()
    if name == 'Ark of Hunger':
        eng.activate_ability(eng.state.active_player, source, 0)
        eng.resolve_until_stable()
    assert obj.zone == Zone.GRAVEYARD
    assert eng.can_cast(eng.state.active_player, obj)
    eng.cast_spell(eng.state.active_player, obj)
    eng.resolve_until_stable()
    if name == 'Ark of Hunger':
        assert eng.state.player_by_id('p2').life == 19
        assert eng.state.player_by_id('p1').life == 21


def test_many_card_window_only_grants_the_milled_pool():
    eng = _engine()
    first, second = _top(eng), _top(eng)
    unrelated = GameObject(_instant(cost='{0}', mv=0), owner_id='p1', zone=Zone.GRAVEYARD)
    eng.state.active_player.graveyard.append(unrelated)
    _window(eng, 'mill 2 cards. until end of turn, you may cast spells from among them.')
    assert all(eng.can_cast(eng.state.active_player, obj) for obj in (first, second))
    assert not eng.can_cast(eng.state.active_player, unrelated)


def test_clone_preserves_graveyard_window_and_land_timing_and_limit():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = _engine()
    obj = _top(eng, land=True)
    _window(eng, 'mill a card. you may play that card this turn.')
    eng = GameEngine(eng.state.clone())
    obj = eng.state.find_object(obj.instance_id)
    player = eng.state.active_player
    assert eng.can_play_land(player, obj)
    eng.state.current_step = 'upkeep'
    assert not eng.can_play_land(player, obj)
    eng.state.current_step = 'main1'
    player.lands_played_this_turn = player.max_lands_per_turn
    assert not eng.can_play_land(player, obj)


@pytest.mark.parametrize("producer", ["mill a card", "reveal the top card of your library"])
def test_cost_and_cast_prohibition_still_apply(producer):
    eng = _engine()
    obj = _top(eng)
    obj.card = _instant(cost='{3}', mv=3)
    _window(eng, producer + '. you may play that card this turn.')
    assert not eng.can_cast(eng.state.active_player, obj)
    eng.state.active_player.mana_pool.add('C', 3)
    assert eng.can_cast(eng.state.active_player, obj)
    _bf(eng, Card(id='Cage', name="Grafdigger's Cage", type_line='Artifact',
                  oracle_text="Creature cards in graveyards and libraries can't enter the battlefield.\nPlayers can't cast spells from graveyards or libraries."))
    eng.recompute_continuous_effects()
    assert not eng.can_cast(eng.state.active_player, obj)


@pytest.mark.parametrize('zone', [Zone.GRAVEYARD, Zone.LIBRARY])
def test_permission_is_held_by_caster_and_expires_on_a_new_visit(zone):
    eng = _engine()
    obj = _top(eng, owner='p2')
    owner = eng.state.player_by_id('p2')
    if zone == Zone.GRAVEYARD:
        owner.library.remove(obj)
        obj.zone = zone
        owner.graveyard.append(obj)
    player = eng.state.player_by_id('p1')
    eng.rules._grant_temp_play_permission(obj, player, 'Grantor', True, None)
    assert eng.can_cast(player, obj)
    assert any(a.get('instance_id') == obj.instance_id for a in eng.legal_actions(player))
    assert not eng.can_cast(owner, obj)
    # RULE 400.7: leaving and returning cannot restore the old permission.
    eng.rules.return_to_hand(obj)
    if zone == Zone.LIBRARY:
        eng.rules.return_to_library(obj)
    else:
        eng.rules.discard_specific(obj)
    assert not eng.can_cast(player, obj)


@pytest.mark.parametrize('producer', ['mill a card', 'reveal the top card of your library'])
@pytest.mark.parametrize('land', [False, True])
def test_conditional_window_filters_the_single_card(producer, land):
    eng = _engine()
    obj = _top(eng, land=land)
    _window(eng, producer + ". if it's an instant card, you may cast it this turn.")
    assert eng.can_cast(eng.state.active_player, obj) is (not land)
    assert not eng.can_play_land(eng.state.active_player, obj)
