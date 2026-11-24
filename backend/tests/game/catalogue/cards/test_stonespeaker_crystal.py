"""Stonespeaker Crystal: real activation costs and any number of player targets."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def board():
    engine = game(players=3, library=20)
    advance_to(engine, 'main1')
    crystal = card(engine, 'Stonespeaker Crystal')
    player = engine.state.player_by_id('p1')
    player.mana_pool.add_many(RICH)
    graves = [filler(engine, 'Grave '+p.id, player=p.id, zone=Zone.GRAVEYARD)
              for p in engine.state.players]
    return engine, crystal, player, graves


def test_fresh_specs_and_binding():
    engine, crystal, player, graves = board()
    a, b = specs_for(crystal.card), specs_for(crystal.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(crystal.activated_abilities) == 1
    assert crystal.activated_abilities[0].effects[0].target_spec.any_number


@pytest.mark.parametrize('chosen', [[], [0], [1, 2], [0, 1, 2]])
def test_zero_one_or_multiple_graveyards_and_draw(chosen):
    engine, crystal, player, graves = board()
    before = len(player.hand)
    engine.activate_ability(player, crystal, 0, targets=[engine.state.players[i] for i in chosen])
    assert crystal.zone == Zone.GRAVEYARD  # sacrifice is paid before resolution
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert len(player.hand) == before + 1
    assert [obj.zone == Zone.EXILE for obj in graves] == [i in chosen for i in range(3)]
    assert crystal.zone == (Zone.EXILE if 0 in chosen else Zone.GRAVEYARD)


def test_clone_after_activation_keeps_all_targets():
    engine, crystal, player, graves = board()
    engine.activate_ability(player, crystal, 0, targets=engine.state.players)
    clone = GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert all(clone.state.find_object(o.instance_id).zone == Zone.EXILE for o in graves)
    assert all(o.zone == Zone.GRAVEYARD for o in graves)


def test_countered_ability_keeps_costs_and_does_not_draw():
    engine, crystal, player, graves = board()
    before = len(player.hand)
    engine.activate_ability(player, crystal, 0, targets=[engine.state.players[1]])
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert crystal.zone == Zone.GRAVEYARD and len(player.hand) == before
    assert all(o.zone == Zone.GRAVEYARD for o in graves)


def test_duplicate_player_targets_rejected_before_payment():
    engine, crystal, player, graves = board()
    with pytest.raises(ValueError):
        engine.activate_ability(player, crystal, 0, targets=[player, player])
    assert crystal.zone == Zone.BATTLEFIELD and not crystal.tapped


def test_native_mana_ability_adds_two_colorless():
    engine, crystal, player, graves = board()
    before = player.mana_pool.to_dict().get('C', 0)
    engine.tap_for_mana(player, crystal)
    assert crystal.tapped and crystal.zone == Zone.BATTLEFIELD
    assert player.mana_pool.to_dict().get('C', 0) == before + 2


@pytest.mark.parametrize('all_illegal', [False, True])
def test_target_legality_is_rechecked_at_resolution(all_illegal):
    engine, crystal, player, graves = board()
    before = len(player.hand)
    targets = [engine.state.players[1]] if all_illegal else engine.state.players[1:]
    engine.activate_ability(player, crystal, 0, targets=targets)
    card(engine, 'Shalai, Voice of Plenty', player='p2')
    engine.resolve_until_stable()
    assert graves[1].zone == Zone.GRAVEYARD
    assert graves[2].zone == (Zone.GRAVEYARD if all_illegal else Zone.EXILE)
    assert len(player.hand) == before + (0 if all_illegal else 1)
