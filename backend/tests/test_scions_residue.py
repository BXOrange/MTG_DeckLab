"""Defending-player card copies, untargeted choices and historical damage."""
import json
import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession
from tests.game.catalogue.cards.test_scions_spellcraft_deck import _game, _card, _filler, _put_on_battlefield, _named, _attack, _activate


def _cane_setup():
    engine = _game(players=3)
    cane = _put_on_battlefield(engine, "Blue Mage's Cane")
    hero = _named(engine, 'Hero')[0]
    hero.summoning_sick = False
    continuous.recompute(engine.state)
    spells = [_filler(engine, f'Their{i}', 'Instant', mv=1, zone=Zone.GRAVEYARD, player=f'p{i}') for i in (2, 3)]
    _attack(engine, [hero])
    return engine, cane, hero, spells


def test_cane_only_offers_defending_players_graveyard():
    engine, cane, hero, spells = _cane_setup()
    assert {o['instance_id'] for o in engine.state.pending_choice['options'] if 'instance_id' in o} == {spells[0].instance_id}


def test_cane_declining_copy_cast_keeps_real_card_exiled_and_removes_copy():
    engine, cane, hero, spells = _cane_setup()
    engine.resolve_pending_choice(str(spells[0].instance_id))
    copy = engine.state.players[0].exile[-1]
    assert copy is not spells[0] and copy.is_copy
    assert engine.state.resolution_play_choice['free'] is False
    engine.resolve_pending_choice('decline')
    assert spells[0].zone == Zone.EXILE and engine.state.find_object(copy.instance_id) is None
    assert not engine.can_cast(engine.state.players[0], spells[0])


def test_cane_copy_is_cast_during_resolution_for_three_and_original_stays_exiled():
    engine, cane, hero, spells = _cane_setup()
    engine.resolve_pending_choice(str(spells[0].instance_id))
    player = engine.state.players[0]
    copy = next(o for o in player.exile if getattr(o, 'is_copy', False))
    player.mana_pool.add('C', 2)
    assert not engine.can_cast(player, copy)
    player.mana_pool.add('C', 1)
    engine.play_resolution_card(player, copy)
    assert player.mana_pool.total() == 0 and copy.zone == Zone.STACK
    assert engine.state.current_step == 'declare_attackers'
    engine.rules.counter_spell(copy)
    engine.rules.check_state_based_actions()
    assert spells[0].zone == Zone.EXILE and engine.state.find_object(copy.instance_id) is None


def _urianger_setup():
    engine = _game()
    urianger = _card(engine, 'Urianger Augurelt')
    secret = _filler(engine, 'Top Secret', 'Instant', mv=2, zone=Zone.LIBRARY)
    _activate(engine, urianger, 0)
    return engine, urianger, secret


def test_urianger_look_precedes_exile_choice_and_is_private():
    engine, urianger, secret = _urianger_setup()
    session = GameSession(engine)
    assert secret.zone == Zone.LIBRARY
    assert secret.name in json.dumps(session.view(perspective='p1'))
    assert secret.name not in json.dumps(session.view(perspective='p2'))
    assert secret.name not in json.dumps(session.observer_view())
    engine.resolve_pending_choice('ok')
    assert secret.zone == Zone.LIBRARY and engine.state.pending_choice['kind'] == 'pay_cost_then'
    engine.resolve_pending_choice('decline')
    assert secret.zone == Zone.LIBRARY and not urianger.exiled_with_ids


def test_urianger_exiles_after_look_and_links_the_card_face_down():
    engine, urianger, secret = _urianger_setup()
    engine.resolve_pending_choice('ok')
    engine.resolve_pending_choice('pay')
    assert secret.zone == Zone.EXILE and secret.face_down_in_exile
    assert secret.instance_id in urianger.exiled_with_ids
    assert secret.name not in json.dumps(GameSession(engine).view(perspective='p2'))


def _mog_setup():
    engine = _game()
    mog = _card(engine, 'Summon: Good King Mog XII')
    engine.resolve_until_stable()
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, chapter=2, controller_id='p1', instance_id=mog.instance_id))
    engine.resolve_until_stable()
    return engine, mog


def test_mog_chooses_on_resolution_without_targeting_shroud_or_ward_token():
    engine, mog = _mog_setup()
    token = _named(engine, 'Moogle')[0]
    token.intrinsic_keywords.update({'shroud', 'ward'})
    spell = _filler(engine, 'Spell', 'Instant', mv=0, zone=Zone.HAND)
    engine.state.current_step = 'main1'
    engine.cast_spell(engine.state.players[0], spell)
    engine.rules.put_triggers_on_stack()
    assert not engine.state.pending_choice
    ability = engine.state.stack[-1]
    assert not ability.targets
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['kind'] == 'choose_objects'
    engine.resolve_pending_choice(str(token.instance_id))
    assert len(_named(engine, 'Moogle')) == 3


def test_mog_excludes_saga_tokens_from_resolution_choice():
    engine, mog = _mog_setup()
    saga_token = engine.rules.copy_permanent('p1', mog)[0]
    engine.resolve_until_stable()
    spell = _filler(engine, 'Spell', 'Instant', mv=0, zone=Zone.HAND)
    engine.state.current_step = 'main1'
    engine.cast_spell(engine.state.players[0], spell)
    engine.resolve_until_stable()
    assert saga_token.instance_id not in {o.get('instance_id') for o in engine.state.pending_choice['options']}


@pytest.mark.parametrize('was_dragon', [True, False])
def test_estinien_counts_dragon_at_damage_time_despite_later_type_changes(was_dragon):
    engine = _game(players=3)
    estinien = _card(engine, 'Estinien Varlineau')
    dealer = _filler(engine, 'Dealer', 'Creature — Dragon' if was_dragon else 'Creature — Elf', power=1, toughness=1)
    engine.rules.deal_damage(engine.state.players[1], 1, source=dealer, combat=True)
    dealer.card.type_line = 'Creature — Elf' if was_dragon else 'Creature — Dragon'
    continuous.recompute(engine.state)
    count = continuous.count_selector(engine.state, 'p1', 'opponents_dealt_combat_damage_by_self_or_dragon_this_turn', source=estinien)
    assert count == int(was_dragon)


def test_estinien_counts_dead_dragon_and_distinct_opponents_but_not_noncombat_damage():
    engine = _game(players=3)
    estinien = _card(engine, 'Estinien Varlineau')
    dragon = _filler(engine, 'Dragon', 'Creature — Dragon', power=1, toughness=1)
    engine.rules.deal_damage(engine.state.players[1], 1, source=dragon, combat=True)
    engine.rules.deal_damage(engine.state.players[1], 1, source=dragon, combat=True)
    engine.rules.deal_damage(engine.state.players[2], 1, source=dragon, combat=False)
    engine.rules.destroy(dragon)
    assert continuous.count_selector(engine.state, 'p1', 'opponents_dealt_combat_damage_by_self_or_dragon_this_turn', source=estinien) == 1


def test_cane_flat_alternative_cost_forces_x_zero_and_cannot_be_replaced():
    engine = _game()
    _put_on_battlefield(engine, "Blue Mage's Cane")
    hero = _named(engine, 'Hero')[0]
    hero.summoning_sick = False
    original = _filler(engine, 'X spell', 'Sorcery', mv=1, zone=Zone.GRAVEYARD, player='p2')
    original.card.mana_cost_string = '{X}{U}'
    _attack(engine, [hero])
    engine.resolve_pending_choice(str(original.instance_id))
    copy = next(o for o in engine.state.players[0].exile if getattr(o, 'is_copy', False))
    player = engine.state.players[0]
    player.mana_pool.add('C', 3)
    offer = next(a for a in engine.resolution_play_actions(player) if a.get('instance_id') == copy.instance_id)
    assert not offer.get('has_x') and offer['max_x'] == 0
    with pytest.raises(ValueError, match='X must be zero'):
        engine.play_resolution_card(player, copy, x=2)
    with pytest.raises(ValueError, match='offered alternative cost'):
        engine.play_resolution_card(player, copy, free=True)
    assert player.mana_pool.total() == 3 and copy.zone == Zone.EXILE


def test_urianger_private_look_acknowledgement_does_not_leak_through_move_log():
    engine, urianger, secret = _urianger_setup()
    session = GameSession(engine, mode='multiplayer', require_setup=False)
    session.apply_action({'type': 'choose', 'option_id': 'ok', 'name': secret.name,
                          'instance_id': secret.instance_id}, actor_id='p1')
    assert session.move_log == ['choose']
    assert secret.name not in json.dumps(session.view(perspective='p2'))
    session.apply_action({'type': 'choose', 'option_id': 'pay'}, actor_id='p1')
    assert secret.name not in json.dumps(session.view(perspective='p2'))
    assert secret.name not in json.dumps(session.observer_view())
