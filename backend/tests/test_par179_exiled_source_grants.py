"""Independent land-grant and cast-permission lifetimes (RULE 400.7j / 611.2).

SNC release notes: https://media.wizards.com/2022/downloads/SNC_Release_Notes/EN_MTGSNC_ReleaseNotes_20220331.pdf
The land can help pay for the spell; an unrelated exile exit leaves its grant intact.
"""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.services.game_session import GameSession


TEXT = ('{2}, Exile this card from your hand: Target land gains "{T}: Add {U}, {B}, or {R}" '
        'until this card is cast from exile. You may cast this card for as long as it remains exiled.')


def setup(text=TEXT, name='Exiled Source', mana='{U}', opponent_land=False):
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = 'main1'
    player = eng.state.player_by_id('p1')
    source = GameObject(Card(id=name, name=name, type_line='Creature', is_creature=True, power=2, toughness=2,
                             mana_cost_string=mana, oracle_text=text), owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(source)
    player.add_to_zone(source, Zone.HAND)
    land = GameObject(Card(id='land', name='Plain Land', type_line='Land', is_land=True),
                      owner_id='p2' if opponent_land else 'p1', zone=Zone.BATTLEFIELD)
    bind_from_catalogue(land)
    eng.state.add_to_battlefield(land)
    player.mana_pool.add('C', 2)
    return eng, player, source, land


def activate(eng, player, source, land, resolve=True):
    eng.activate_ability(player, source, targets=[land])
    assert source.zone == Zone.EXILE
    assert source not in player.hand
    assert eng.state.stack
    if resolve:
        eng.resolve_until_stable()
        eng.recompute_continuous_effects()


@pytest.mark.parametrize('name', ['Glamorous Outlaw', 'Rakish Revelers', 'Shattered Seraph', 'Masked Bandits',
                                  'Emrakul, the Exigent Doom'])
def test_real_cluster_cards_model_and_bind(name):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert card is not None
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(obj)
    assert any(a.cost.exile_self_from_hand for a in obj.activated_abilities)


def test_spara_keeps_its_separate_restriction_gap():
    card = CardDatabase(DEFAULT_DB_PATH).get_card("Spara's Adjudicators")
    result = parse_oracle(card)
    assert not result.modeled
    assert all('until this card is cast from exile' not in line for line in result.unclaimed)


def test_activation_uses_stack_and_can_grant_to_opponents_land():
    eng, player, source, land = setup(opponent_land=True)
    assert eng.can_activate(player, source, source.activated_abilities[0])
    actions = eng.legal_actions(player)
    assert any(action.get('type') == 'activate_ability' and action.get('instance_id') == source.instance_id for action in actions)
    activate(eng, player, source, land, resolve=False)
    assert not land.granted_mana_options
    eng.resolve_until_stable()
    assert land.granted_mana_options == [{'U': 1}, {'B': 1}, {'R': 1}]
    assert eng._has_temp_play_permission(source, player)
    assert not eng._has_temp_play_permission(source, eng.state.player_by_id('p2'))
    assert not eng.can_activate(player, source, source.activated_abilities[0])


def test_granted_mana_pays_real_cast_and_grant_ends_only_after_cost_payment():
    eng, player, source, land = setup()
    activate(eng, player, source, land)
    assert eng.can_cast(player, source, assume_mana_available=True)
    assert eng.tap_for_mana(player, land) == {'U': 1}
    eng.cast_spell(player, source)
    assert source.zone == Zone.STACK
    assert not land.granted_mana_options
    assert not eng.state.floating_statics
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD


def test_emrakul_grant_adds_two_colorless_not_two_choices():
    text = TEXT.replace('{2}', '{3}', 1).replace('{U}, {B}, or {R}', '{C}{C}')
    eng, player, source, land = setup(text=text, mana='{2}')
    player.mana_pool.add('C', 1)
    activate(eng, player, source, land)
    assert eng.tap_for_mana(player, land) == {'C': 2}
    eng.cast_spell(player, source)
    assert not land.granted_mana_options


def test_source_unrelated_exit_and_reentry_does_not_end_grant_or_revive_permission():
    eng, player, source, land = setup()
    activate(eng, player, source, land)
    eng.rules.return_to_hand(source)
    eng.recompute_continuous_effects()
    assert land.granted_mana_options
    eng.rules.exile(source)
    eng.recompute_continuous_effects()
    assert land.granted_mana_options
    assert not eng._has_temp_play_permission(source, player)
    assert not eng.can_cast(player, source)


def test_later_exile_visit_cast_does_not_end_original_grant():
    eng, player, source, land = setup()
    activate(eng, player, source, land)
    original = eng.state.floating_statics[0]
    eng.rules.return_to_hand(source)
    eng.rules.exile(source)
    eng.rules._grant_temp_play_permission(source, player, 'Other effect', False, None)
    eng.state.temp_play_permission_standing.add(source.instance_id)
    player.mana_pool.add('U', 1)
    eng.cast_spell(player, source)
    assert original in eng.state.floating_statics
    assert land.granted_mana_options


def test_target_land_zone_change_does_not_transfer_grant_to_new_visit():
    eng, player, source, land = setup()
    activate(eng, player, source, land)
    eng.rules.return_to_hand(land)
    player.hand.remove(land)
    land.zone = Zone.BATTLEFIELD
    eng.state.add_to_battlefield(land)
    eng.recompute_continuous_effects()
    assert not land.granted_mana_options
    assert eng._has_temp_play_permission(source, player)


def test_source_zone_exit_before_resolution_does_not_grant_to_new_exile_visit():
    eng, player, source, land = setup()
    activate(eng, player, source, land, resolve=False)
    eng.rules.return_to_hand(source)
    eng.rules.exile(source)
    eng.resolve_until_stable()
    assert land.granted_mana_options
    assert not eng._has_temp_play_permission(source, player)


def test_clone_pending_activation_and_undo_cast_restore_independent_lifetimes():
    eng, player, source, land = setup()
    activate(eng, player, source, land, resolve=False)
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    cloned_source = clone.state.find_object(source.instance_id)
    cloned_land = clone.state.find_object(land.instance_id)
    cloned_player = clone.state.player_by_id('p1')
    assert clone._has_temp_play_permission(cloned_source, cloned_player)
    assert cloned_land.granted_mana_options
    session = GameSession(clone)
    session._snapshot('before cast')
    clone.tap_for_mana(cloned_player, cloned_land)
    clone.cast_spell(cloned_player, cloned_source)
    assert not cloned_land.granted_mana_options
    session.rewind()
    restored = session.engine
    restored_source = restored.state.find_object(source.instance_id)
    restored_land = restored.state.find_object(land.instance_id)
    assert restored_source.zone == Zone.EXILE
    restored.recompute_continuous_effects()
    assert restored_land.granted_mana_options
    assert restored._has_temp_play_permission(restored_source, restored.state.player_by_id('p1'))
    assert eng.state.stack and not land.granted_mana_options


def test_adversarial_quote_and_duration_fail_closed():
    assert parse_effect_body('target land gains "invent a purple elephant" until this card is cast from exile') is None
    assert parse_effect_body('target land gains "{t}: add {u}" until this card leaves exile') is None


def test_invalid_target_and_insufficient_mana_leave_hand_card_unpaid():
    eng, player, source, land = setup()
    with pytest.raises(ValueError):
        eng.activate_ability(player, source, targets=[source])
    assert source in player.hand and player.mana_pool.total() == 2
    player.mana_pool.empty()
    assert not eng.can_activate(player, source, source.activated_abilities[0])
    with pytest.raises(ValueError):
        eng.activate_ability(player, source, targets=[land])
    assert source in player.hand


def test_only_target_leaves_before_resolution_fizzles_permission_too():
    eng, player, source, land = setup()
    activate(eng, player, source, land, resolve=False)
    eng.rules.return_to_hand(land)
    eng.resolve_until_stable()
    assert not eng._has_temp_play_permission(source, player)
    assert not eng.state.floating_statics


def test_standing_permission_and_land_grant_survive_turn_cleanup():
    eng, player, source, land = setup()
    activate(eng, player, source, land)
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert land.granted_mana_options
    assert eng._has_temp_play_permission(source, player)


def test_compound_quoted_grant_announces_one_target_for_all_statics():
    text = TEXT.replace('{T}: Add {U}, {B}, or {R}', 'When this permanent enters or leaves the battlefield, draw a card.')
    eng, player, source, land = setup(text=text)
    assert len(source.activated_abilities[0].effects[0].extra_statics) == 1
    activate(eng, player, source, land)
    assert len(eng.state.floating_statics) == 2
    assert all(ability.object_ids == [land.instance_id] for ability in eng.state.floating_statics)
