"""RULE 201.5b / 605.1a: borrowed nonbasic-land abilities use the recipient."""
import pytest

from mtg_analyzer.game import continuous, mana_abilities
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_sultai_arisen_deck import _game, _card, _filler, _enter, _answer


def _borrow(name):
    engine = _game()
    donor = _card(engine, name, zone=Zone.GRAVEYARD)
    bearer = _filler(engine, 'Borrower', 'Creature — Bear', power=2, toughness=2)
    steward = _card(engine, 'Steward of the Harvest')
    _enter(engine, steward)
    _answer(engine, prefer={donor.instance_id})
    continuous.recompute(engine.state)
    bearer.summoning_sick = False
    return engine, engine.state.player_by_id('p1'), donor, bearer, steward


def test_steward_borrows_painland_mana_and_damage_uses_creature_source():
    engine, player, donor, bearer, steward = _borrow('Yavimaya Coast')
    abilities = mana_abilities.mana_abilities_for(bearer)
    index = next(i for i, a in enumerate(abilities) if a.self_damage)
    engine.tap_for_mana(player, bearer, ability_index=index, option_index=0)
    assert player.life == 19
    assert player.mana_pool.total() == 1 and bearer.tapped
    damage = [e for e in engine.state.event_log if e.type == EventType.DAMAGE][-1]
    assert damage.get('source_id') == bearer.instance_id
    assert donor.zone == Zone.EXILE


def test_steward_borrows_coffers_cost_and_counts_players_swamps():
    engine, player, donor, bearer, steward = _borrow('Cabal Coffers')
    for _ in range(3):
        _card(engine, 'Swamp')
    continuous.recompute(engine.state)
    player.mana_pool.add('C', 2)
    engine.tap_for_mana(player, bearer)
    assert player.mana_pool.total() == 3 and player.mana_pool.pool.get('B', 0) == 3
    assert bearer.tapped and donor.zone == Zone.EXILE


def test_steward_borrowed_tap_mana_obeys_recipients_summoning_sickness():
    engine, player, donor, bearer, steward = _borrow('Yavimaya Coast')
    bearer.summoning_sick = True
    with pytest.raises(ValueError):
        engine.tap_for_mana(player, bearer)
    assert player.mana_pool.total() == 0 and not bearer.tapped


def test_steward_borrows_war_room_draw_cost_from_recipient_controller():
    engine, player, donor, bearer, steward = _borrow('War Room')
    commander = _card(engine, 'Kotis, Sibsig Champion', zone=Zone.COMMAND)
    commander.is_commander = True
    continuous.recompute(engine.state)
    before_hand = len(player.hand)
    player.mana_pool.add('C', 3)
    assert bearer.granted_activated_abilities
    index = len(bearer.activated_abilities)
    engine.activate_ability(player, bearer, index)
    engine.resolve_until_stable()
    assert len(player.hand) == before_hand + 1
    assert player.life == 17 and bearer.tapped
    assert donor.zone == Zone.EXILE


def test_steward_borrowed_land_sacrifice_cost_sacrifices_recipient():
    engine, player, donor, bearer, steward = _borrow('Myriad Landscape')
    player.mana_pool.add('C', 2)
    index = len(bearer.activated_abilities)
    engine.activate_ability(player, bearer, index)
    assert bearer.zone == Zone.GRAVEYARD
    assert donor.zone == Zone.EXILE and steward.zone == Zone.BATTLEFIELD
