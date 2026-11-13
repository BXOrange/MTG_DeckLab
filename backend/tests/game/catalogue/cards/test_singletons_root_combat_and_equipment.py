"""Runtime legality, ordered graveyard, blocked status, and Equipment costs."""
import pytest
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.effects.attachments_transforms import TapEffect
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object


def combat_phase(engine):
    engine.state.current_phase = 'combat'
    engine.state.current_step = 'begin_combat'


def bear(engine, owner='p1', name='Bear'):
    obj = battlefield_object(engine, owner, name, 'Creature — Bear', is_creature=True, power=4, toughness=4)
    obj.summoning_sick = False
    return obj


@pytest.mark.parametrize('name', ["Arcum's Sleigh", 'Kjeldoran Guard', 'Ashen Ghoul', 'Cinder Crawler', 'Fishing Pole'])
def test_authored_specs_fresh_and_bound(name):
    engine = _game()
    obj = _card(engine, name)
    a, b = specs_for(obj.card), specs_for(obj.card)
    assert a and all(x is not y for x, y in zip(a, b))
    assert obj.activated_abilities or obj.static_effects


@pytest.mark.parametrize('name,snow,allowed', [("Arcum's Sleigh", False, False), ("Arcum's Sleigh", True, True),
                                                ('Kjeldoran Guard', False, True), ('Kjeldoran Guard', True, False)])
def test_snow_defender_gate_and_combat_timing(name, snow, allowed):
    engine = _game()
    player = engine.state.players[0]
    source = _card(engine, name)
    source.summoning_sick = False
    target = bear(engine)
    _card(engine, 'Snow-Covered Forest' if snow else 'Forest', 'p2')
    player.mana_pool.add('C', 2)
    assert not engine.can_activate(player, source, source.activated_abilities[0])
    combat_phase(engine)
    assert engine.can_activate(player, source, source.activated_abilities[0]) is allowed
    if allowed:
        engine.activate_ability(player, source, targets=[target])
        engine.resolve_until_stable()
        engine.recompute_continuous_effects()
        if name == "Arcum's Sleigh":
            assert 'vigilance' in target.granted_keywords
        else:
            assert target.power == 5
            engine.rules.return_to_hand(target)
            engine.resolve_until_stable()
            assert source.zone == Zone.GRAVEYARD


def test_multiplayer_guard_as_attacker_uses_its_specific_defender():
    engine = _game(3)
    player = engine.state.players[0]
    source = _card(engine, 'Kjeldoran Guard')
    source.summoning_sick = False
    _card(engine, 'Snow-Covered Forest', 'p2')
    combat_phase(engine)
    assert engine.can_activate(player, source, source.activated_abilities[0])
    source.attacking = True
    source.combat_defender = {'kind': 'player', 'id': 'p2'}
    assert not engine.can_activate(player, source, source.activated_abilities[0])
    source.combat_defender = {'kind': 'player', 'id': 'p3'}
    assert engine.can_activate(player, source, source.activated_abilities[0])


def test_ashen_ghoul_counts_only_creature_cards_above_it_during_own_upkeep():
    engine = _game()
    player = engine.state.players[0]
    _card(engine, 'Grizzly Bears', zone=Zone.GRAVEYARD)  # below the Ghoul
    ghoul = _card(engine, 'Ashen Ghoul', zone=Zone.GRAVEYARD)
    for name in ('Grizzly Bears', 'Grizzly Bears', 'Forest'):
        _card(engine, name, zone=Zone.GRAVEYARD)
    player.mana_pool.add('B', 1)
    engine.state.current_step = 'upkeep'
    assert not engine.can_activate(player, ghoul, ghoul.activated_abilities[0])
    _card(engine, 'Grizzly Bears', zone=Zone.GRAVEYARD)
    engine.state.current_step = 'main1'
    assert not engine.can_activate(player, ghoul, ghoul.activated_abilities[0])
    engine.state.current_step = 'upkeep'
    assert engine.can_activate(player, ghoul, ghoul.activated_abilities[0])
    engine.activate_ability(player, ghoul)
    engine.resolve_until_stable()
    assert ghoul.zone == Zone.BATTLEFIELD
    assert 'haste' in ghoul.intrinsic_keywords


def test_cinder_remains_blocked_after_last_blocker_removed_from_combat():
    engine = _game()
    player, opponent = engine.state.players
    crawler = _card(engine, 'Cinder Crawler')
    crawler.summoning_sick = False
    blocker = bear(engine, opponent.id)
    combat_phase(engine)
    engine.state.current_step = 'declare_attackers'
    engine.declare_attackers(player, [crawler])
    player.mana_pool.add('R', 1)
    assert not engine.can_activate(player, crawler, crawler.activated_abilities[0])
    engine.state.current_step = 'declare_blockers'
    engine.declare_blockers(opponent, [{'blocker': blocker, 'attacker': crawler}])
    TapEffect._remove_from_combat(engine.rules.context, blocker)
    assert not crawler.blocked_by and crawler.is_blocked
    assert engine.state.clone().find_object(crawler.instance_id).is_blocked
    assert engine.can_activate(player, crawler, crawler.activated_abilities[0])
    engine.activate_ability(player, crawler)
    engine.resolve_until_stable()
    assert crawler.power == 2
    before = opponent.life
    engine._deal_combat_damage_step(False)
    assert opponent.life == before
    engine._clear_combat()
    assert not crawler.is_blocked
    assert not engine.can_activate(player, crawler, crawler.activated_abilities[0], assume_mana_available=True)


def test_fishing_pole_taps_two_distinct_objects_and_untap_makes_one_fish():
    engine = _game()
    player = engine.state.players[0]
    host = bear(engine)
    pole = _card(engine, 'Fishing Pole')
    pole.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    player.mana_pool.add('C', 1)
    assert len(host.granted_activated_abilities) == 1
    pole.tapped = True
    assert not engine.can_activate(player, host, host.granted_activated_abilities[0])
    pole.tapped = False
    engine.activate_ability(player, host)
    assert host.tapped and pole.tapped
    engine.resolve_until_stable()
    assert pole.counters.get('bait') == 1
    assert not host.counters
    engine.rules.set_tapped(host, False)
    engine.resolve_until_stable()
    assert not pole.counters.get('bait', 0)
    fish = [obj for obj in engine.state.battlefield if obj.is_token]
    assert len(fish) == 1 and fish[0].name == 'Fish'
    engine.rules.set_tapped(host, True)
    engine.rules.set_tapped(host, False)
    engine.resolve_until_stable()
    assert len([obj for obj in engine.state.battlefield if obj.is_token]) == 1


@pytest.mark.parametrize('before_resolution', [True, False])
def test_guard_delayed_sacrifice_does_not_take_a_new_guard_visit(before_resolution):
    engine = _game()
    player = engine.state.players[0]
    guard = _card(engine, 'Kjeldoran Guard')
    guard.summoning_sick = False
    target = bear(engine)
    combat_phase(engine)
    engine.activate_ability(player, guard, targets=[target])
    if not before_resolution:
        engine.resolve_until_stable()
    engine.rules.exile(guard)
    engine.rules.return_from_graveyard(guard, 'battlefield')
    engine.resolve_until_stable()
    engine.rules.return_to_hand(target)
    engine.resolve_until_stable()
    assert guard.zone == Zone.BATTLEFIELD


def test_fishing_pole_does_not_add_bait_to_a_later_equipment_visit():
    engine = _game()
    player = engine.state.players[0]
    host = bear(engine)
    pole = _card(engine, 'Fishing Pole')
    pole.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    player.mana_pool.add('C', 1)
    engine.activate_ability(player, host)
    engine.rules.exile(pole)
    engine.rules.return_from_graveyard(pole, 'battlefield')
    engine.resolve_until_stable()
    assert pole.zone == Zone.BATTLEFIELD
    assert not pole.counters and not host.counters


def test_granted_pole_ability_can_tap_an_opponents_equipment_but_fish_belongs_to_equipment_controller():
    engine = _game()
    player, opponent = engine.state.players
    host = bear(engine)
    pole = _card(engine, 'Fishing Pole', opponent.id)
    pole.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    player.mana_pool.add('C', 1)
    engine.activate_ability(player, host)
    engine.resolve_until_stable()
    assert pole.tapped and host.tapped and pole.counters.get('bait') == 1
    engine.rules.set_tapped(host, False)
    engine.resolve_until_stable()
    fish = [o for o in engine.state.battlefield if o.is_token]
    assert len(fish) == 1 and fish[0].controller_id == opponent.id
