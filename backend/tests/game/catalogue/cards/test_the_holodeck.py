"""The Holodeck shares one own-turn play across graveyard and outside game."""
import pytest
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.sideboard import load_sideboard, outside_play_grant_for
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import card, game, RICH
from tests.support.star_trek import advance_to


def outside(engine,name,player='p1'):
    actor=engine.state.player_by_id(player)
    load_sideboard(actor,[CardDatabase(DB_PATH).get_card(name)])
    return actor.sideboard[-1]


def board():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'The Holodeck')
    gy_spell=card(engine,'Ornithopter',zone=Zone.GRAVEYARD)
    gy_land=card(engine,'Island',zone=Zone.GRAVEYARD)
    out_spell=outside(engine,'Sol Ring'); out_land=outside(engine,'Forest')
    return engine,source,gy_spell,gy_land,out_spell,out_land


def cast(engine,obj,player='p1'):
    actor=engine.state.player_by_id(player); actor.mana_pool.add_many(RICH)
    engine.cast_spell(actor,obj); engine.resolve_until_stable()


def test_fresh_specs_and_bound_cross_zone_play_permission():
    engine,source,*_=board(); a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.static_effects)==1 and source.static_effects[0].outside_game


@pytest.mark.parametrize('choice',['gy_spell','out_spell','gy_land','out_land'])
def test_all_four_routes_consume_the_same_once_per_turn_use(choice):
    engine,source,gy_spell,gy_land,out_spell,out_land=board()
    options={'gy_spell':gy_spell,'out_spell':out_spell,'gy_land':gy_land,'out_land':out_land}
    selected=options[choice]; player=engine.state.players[0]
    if choice.endswith('land'): engine.play_land(player,selected)
    else: cast(engine,selected)
    assert selected.zone==Zone.BATTLEFIELD and selected not in player.sideboard
    assert source.cross_zone_play_used_turn==engine.state.internal_turn.number
    for name,obj in options.items():
        if name==choice: continue
        assert not (engine.can_play_land(player,obj) if name.endswith('land') else engine.can_cast(player,obj))


def test_normal_hand_play_does_not_use_holodeck_permission():
    engine,source,gy_spell,gy_land,out_spell,out_land=board()
    normal=card(engine,'Ornithopter',zone=Zone.HAND); cast(engine,normal)
    assert source.cross_zone_play_used_turn is None
    assert engine.can_cast(engine.state.players[0],gy_spell)


def test_only_permanent_spells_are_allowed_from_either_zone():
    engine,source,*_=board(); player=engine.state.players[0]; player.mana_pool.add_many(RICH)
    for obj in [card(engine,'Lightning Bolt',zone=Zone.GRAVEYARD),outside(engine,'Lightning Bolt')]:
        assert not engine.can_cast(player,obj,targets=[engine.state.players[1]])


def test_spell_cost_and_failed_cast_do_not_consume_use():
    engine,source,gy_spell,gy_land,out_spell,out_land=board(); player=engine.state.players[0]
    assert not engine.can_cast(player,out_spell)
    with pytest.raises(ValueError): engine.cast_spell(player,out_spell)
    assert source.cross_zone_play_used_turn is None and out_spell in player.sideboard
    cast(engine,out_spell)


def test_countered_spell_still_consumes_use():
    engine,source,gy_spell,gy_land,out_spell,out_land=board(); player=engine.state.players[0]
    player.mana_pool.add('C',1); engine.cast_spell(player,out_spell)
    engine.rules.counter_spell(out_spell); engine.resolve_until_stable()
    assert out_spell.zone==Zone.GRAVEYARD and not engine.can_cast(player,gy_spell)


def test_land_drop_limit_still_applies_and_does_not_spend_permission_on_failed_play():
    engine,source,gy_spell,gy_land,out_spell,out_land=board(); player=engine.state.players[0]
    normal=card(engine,'Mountain',zone=Zone.HAND); engine.play_land(player,normal)
    assert not engine.can_play_land(player,out_land)
    with pytest.raises(ValueError): engine.play_land(player,out_land)
    assert source.cross_zone_play_used_turn is None
    assert engine.can_cast(player,gy_spell)


def test_outside_land_is_offered_in_legal_actions_and_leaves_sideboard_when_played():
    engine,source,gy_spell,gy_land,out_spell,out_land=board(); player=engine.state.players[0]
    assert any(a['type']=='play_land' and a.get('instance_id')==out_land.instance_id
               for a in engine.legal_actions(player))
    engine.play_land(player,out_land)
    assert out_land not in player.sideboard and out_land in engine.state.battlefield


def test_own_turn_gate_also_prevents_flash_permanents_on_other_turns():
    engine,source,*_=board(); player=engine.state.players[0]; player.mana_pool.add_many(RICH)
    gy=card(engine,'Shimmer Myr',zone=Zone.GRAVEYARD); out=outside(engine,'Shimmer Myr')
    engine.state.active_player_index=1
    assert not engine.can_cast(player,gy) and not engine.can_cast(player,out)
    assert outside_play_grant_for(engine.state,player,out) is None


def test_other_players_cards_do_not_get_your_permission():
    engine,source,*_=board(); player=engine.state.players[0]; player.mana_pool.add_many(RICH)
    foreign=outside(engine,'Sol Ring',player='p2')
    assert not engine.can_cast(player,foreign)
    assert outside_play_grant_for(engine.state,player,foreign) is None


@pytest.mark.parametrize('change',['exile','phase','abilities'])
def test_permission_ends_when_source_is_absent_or_loses_ability(change):
    engine,source,gy_spell,gy_land,out_spell,out_land=board()
    if change=='exile': engine.rules.exile(source)
    elif change=='phase':
        from mtg_analyzer.game.effects.attachments_transforms import PhaseOutEffect
        PhaseOutEffect(target=source).apply(engine.rules.context)
    else:
        from mtg_analyzer.game.effects.core import EffectRegistry
        marker=EffectRegistry.create('remove_all_abilities',{'affects':'self'}); marker.source=source
        source.static_effects.append(marker)
    engine.recompute_continuous_effects(); player=engine.state.players[0]
    assert not engine.can_cast(player,gy_spell) and not engine.can_play_land(player,out_land)


def test_blink_creates_a_fresh_permission_in_the_same_turn():
    engine,source,gy_spell,gy_land,out_spell,out_land=board(); cast(engine,gy_spell)
    engine.rules.exile(source); engine.rules.return_from_graveyard(source,'battlefield')
    assert source.cross_zone_play_used_turn is None
    cast(engine,out_spell); assert out_spell.zone==Zone.BATTLEFIELD


def test_permission_renews_next_own_turn_even_when_untap_step_is_skipped():
    engine,source,gy_spell,gy_land,out_spell,out_land=board(); cast(engine,gy_spell)
    from mtg_analyzer.game.effects.core import EffectRegistry
    marker=EffectRegistry.create('skip_untap_step',{}); marker.source=source
    source.static_effects.append(marker); engine.recompute_continuous_effects()
    prior=engine.state.internal_turn.number
    for _ in range(3):
        advance_to(engine,'cleanup'); engine.advance_step(); advance_to(engine,'main1')
    assert engine.state.active_player.id=='p1' and engine.state.internal_turn.number>prior
    assert source.graveyard_casts_this_turn==1  # every intervening untap step was skipped
    assert outside_play_grant_for(engine.state,engine.state.players[0],out_spell) is not None
    cast(engine,out_spell); assert out_spell.zone==Zone.BATTLEFIELD


@pytest.mark.parametrize('origin',['outside','graveyard'])
def test_modal_land_face_uses_same_permission_and_does_not_allow_sorcery_front(origin):
    engine,source,gy_spell,gy_land,out_spell,out_land=board(); player=engine.state.players[0]
    name='Sea Gate Restoration // Sea Gate, Reborn'
    obj=outside(engine,name) if origin=='outside' else card(engine,name,zone=Zone.GRAVEYARD)
    player.mana_pool.add_many(RICH)
    assert not engine.can_cast(player,obj)
    assert engine.can_play_land(player,obj,face='back')
    engine.play_land(player,obj,face='back')
    assert obj.zone==Zone.BATTLEFIELD and not engine.can_cast(player,gy_spell)


def test_clone_preserves_outside_cards_and_shared_consumption():
    engine,source,gy_spell,gy_land,out_spell,out_land=board()
    clone=GameEngine(engine.state.clone()); copied=clone.state.find_object(out_land.instance_id)
    clone.play_land(clone.state.players[0],copied)
    assert not clone.can_cast(clone.state.players[0],clone.state.find_object(gy_spell.instance_id))
    assert out_land in engine.state.players[0].sideboard and source.cross_zone_play_used_turn is None


@pytest.mark.parametrize('origin',['outside','graveyard'])
def test_permanent_front_does_not_allow_casting_its_nonpermanent_back(origin):
    engine,source,*_=board(); player=engine.state.players[0]; player.mana_pool.add_many(RICH)
    name='Blex, Vexing Pest // Search for Blex'
    obj=outside(engine,name) if origin=='outside' else card(engine,name,zone=Zone.GRAVEYARD)
    assert engine.can_cast(player,obj) and not engine.can_cast(player,obj,face='back')


def test_control_change_grants_permission_to_current_controller_only_on_their_turn():
    engine,source,gy_spell,gy_land,out_spell,out_land=board(); player=engine.state.players[1]
    own=outside(engine,'Ornithopter',player='p2')
    source.controller_id='p2'; engine.state.active_player_index=1; engine.recompute_continuous_effects()
    assert engine.can_cast(player,own)
    assert not engine.can_cast(engine.state.players[0],gy_spell)
    cast(engine,own,player='p2')
    assert own.controller_id=='p2' and source.cross_zone_play_used_turn==engine.state.internal_turn.number
