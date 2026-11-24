"""Nog's permanent subtype, stat and ability changes run through real activations."""
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, RICH, attack
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    nog=card(engine,'Nog, Ambitious Cadet')
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    return engine,nog,player


def level(engine,nog,player,index):
    engine.activate_ability(player,nog,index)
    engine.resolve_until_stable()


def officer(engine,nog,player):
    level(engine,nog,player,0); level(engine,nog,player,1)


def test_fresh_specs_binding_native_menace():
    engine,nog,player=board()
    a,b=specs_for(nog.card),specs_for(nog.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(nog.activated_abilities)==2 and combat.has(nog,'menace')


def test_first_level_replaces_creature_types_and_sets_base_stats():
    engine,nog,player=board()
    level(engine,nog,player,0)
    assert nog.has_subtype('Ferengi') and nog.has_subtype('Scout') and not nog.has_subtype('Rogue')
    assert (nog.power,nog.toughness)==(3,4) and combat.has(nog,'menace')
    assert len(nog.granted_triggered_abilities)==1


def test_second_activation_before_scout_does_nothing():
    engine,nog,player=board()
    level(engine,nog,player,1)
    assert nog.has_subtype('Rogue') and not nog.has_subtype('Officer')
    land=card(engine,'Forest',zone=Zone.GRAVEYARD)
    assert not engine.can_play_land(player,land)


def test_officer_retains_scout_stats_and_surveil_trigger():
    engine,nog,player=board()
    officer(engine,nog,player)
    assert nog.has_subtype('Officer') and nog.has_subtype('Ferengi')
    assert not nog.has_subtype('Rogue') and not nog.has_subtype('Scout')
    assert (nog.power,nog.toughness)==(3,4) and len(nog.granted_triggered_abilities)==1


def test_officer_plays_two_graveyard_lands_but_no_third():
    engine,nog,player=board(); officer(engine,nog,player)
    lands=[card(engine,name,zone=Zone.GRAVEYARD) for name in ['Forest','Island','Mountain']]
    for land in lands[:2]:
        assert engine.can_play_land(player,land)
        engine.play_land(player,land)
        assert land.zone==Zone.BATTLEFIELD
    assert not engine.can_play_land(player,lands[2])


def test_officer_cannot_cast_nonland_from_graveyard():
    engine,nog,player=board(); officer(engine,nog,player)
    creature=card(engine,'Serra Angel',zone=Zone.GRAVEYARD)
    assert not engine.can_cast(player,creature)


def test_repeated_failed_levels_do_not_duplicate_land_allowance_or_trigger():
    engine,nog,player=board(); officer(engine,nog,player)
    level(engine,nog,player,0); level(engine,nog,player,1)
    assert len(nog.granted_triggered_abilities)==1
    lands=[card(engine,'Forest',zone=Zone.GRAVEYARD) for _ in range(3)]
    engine.play_land(player,lands[0]); engine.play_land(player,lands[1])
    assert not engine.can_play_land(player,lands[2])


def test_scout_tapping_attacks_and_surveys_two():
    engine,nog,player=board(); level(engine,nog,player,0)
    before=len(player.graveyard)
    attack(engine,[nog])
    assert nog.tapped and engine.state.pending_choice['kind']=='surveil'
    while engine.state.pending_choice:
        choice=engine.state.pending_choice
        chosen=next(o['id'] for o in choice['options'] if o['id']!='decline')
        engine.resolve_pending_choice(chosen)
    assert len(player.graveyard)==before+2


def test_source_leaving_removes_permission_and_additional_land_play():
    engine,nog,player=board(); officer(engine,nog,player)
    engine.rules.exile(nog); engine.recompute_continuous_effects()
    land=card(engine,'Forest',zone=Zone.GRAVEYARD)
    assert not engine.can_play_land(player,land)


def test_blink_returns_printed_rogue_and_removes_grants():
    engine,nog,player=board(); officer(engine,nog,player)
    engine.rules.exile(nog); engine.rules.return_from_graveyard(nog,'battlefield')
    engine.recompute_continuous_effects()
    assert nog.has_subtype('Rogue') and not nog.has_subtype('Officer')
    assert not nog.granted_triggered_abilities
    land=card(engine,'Forest',zone=Zone.GRAVEYARD)
    assert not engine.can_play_land(player,land)


def test_clone_preserves_both_permanent_levels():
    engine,nog,player=board(); officer(engine,nog,player)
    clone=GameEngine(engine.state.clone()); clone.recompute_continuous_effects()
    copied=clone.state.find_object(nog.instance_id)
    assert copied.has_subtype('Officer') and (copied.power,copied.toughness)==(3,4)
    land=card(clone,'Forest',zone=Zone.GRAVEYARD)
    assert clone.can_play_land(clone.state.player_by_id('p1'),land)


def test_gains_survive_cleanup():
    engine,nog,player=board(); officer(engine,nog,player)
    advance_to(engine,'cleanup'); engine.recompute_continuous_effects()
    assert nog.has_subtype('Officer') and (nog.power,nog.toughness)==(3,4)
    assert len(nog.granted_triggered_abilities)==1


def test_conditions_are_checked_when_abilities_resolve():
    engine,nog,player=board()
    engine.activate_ability(player,nog,1)
    engine.activate_ability(player,nog,0)
    engine.resolve_until_stable()
    assert nog.has_subtype('Officer') and (nog.power,nog.toughness)==(3,4)


def test_two_pending_first_levels_grant_only_one_surveil_trigger():
    engine,nog,player=board()
    engine.activate_ability(player,nog,0); engine.activate_ability(player,nog,0)
    engine.resolve_until_stable()
    assert nog.has_subtype('Scout') and len(nog.granted_triggered_abilities)==1


def test_officers_abilities_follow_current_controller():
    engine,nog,player=board(); officer(engine,nog,player)
    nog.controller_id='p2'
    engine.recompute_continuous_effects()
    engine.state.active_player_index=1
    other=engine.state.player_by_id('p2')
    ownland=card(engine,'Forest',zone=Zone.GRAVEYARD)
    lands=[card(engine,'Forest',player='p2',zone=Zone.GRAVEYARD) for _ in range(3)]
    assert not engine.can_play_land(player,ownland)
    engine.play_land(other,lands[0]); engine.play_land(other,lands[1])
    assert not engine.can_play_land(other,lands[2])


def test_ability_loss_suppresses_graveyard_permission():
    engine,nog,player=board(); officer(engine,nog,player)
    aura=card(engine,'Darksteel Mutation'); aura.attached_to=nog.instance_id
    engine.recompute_continuous_effects()
    land=card(engine,'Forest',zone=Zone.GRAVEYARD)
    assert not engine.can_play_land(player,land)
    assert not nog.granted_triggered_abilities
