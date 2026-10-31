"""PAR-198: instead replaces the original instruction and its announcement."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import game,card,filler,cast,RICH,main_phase
from tests.test_par118_exile_hand_time_counters import _db_card

NAMES=('Desolation Angel','Desolation Giant','Ether Well','Feed the Clan','Fight with Fire','Grizzly Fate',
       'Mysteries of the Deep',"Predator's Howl",'Ray of Enfeeblement','Ritual of Hope','Take the Fall','We Say Thee Nay!')

@pytest.mark.parametrize('name',NAMES)
def test_named_cards_are_fully_modeled(name):
    p=parse_oracle(_db_card(name))
    assert p.modeled,p.unclaimed

@pytest.mark.parametrize('name',('Desolation Angel','Desolation Giant'))
@pytest.mark.parametrize('kicked',(0,1))
@pytest.mark.parametrize('leave',(False,True))
def test_actual_etb_destruction_replaces_scope_and_keeps_source_cast_choices(name,kicked,leave):
    eng=game();main_phase(eng)
    p1=eng.state.active_player;p1.mana_pool.add_many(RICH)
    land=name=='Desolation Angel'
    mine=filler(eng,'Mine',type_line='Land' if land else 'Creature',power=None if land else 2,toughness=None if land else 2)
    theirs=filler(eng,'Theirs',player='p2',type_line='Land' if land else 'Creature',power=None if land else 2,toughness=None if land else 2)
    obj=card(eng,name,zone=Zone.HAND)
    eng.cast_spell(p1,obj,kicked=kicked)
    eng.rules.resolve_top_of_stack()
    eng.rules.put_triggers_on_stack()
    if leave:
        eng.rules.return_to_hand(obj)
    eng.resolve_until_stable()
    assert mine.zone==Zone.GRAVEYARD
    assert theirs.zone==(Zone.GRAVEYARD if kicked else Zone.BATTLEFIELD)
    if not leave:
        assert obj.zone==Zone.BATTLEFIELD

@pytest.mark.parametrize('ferocious',(False,True))
def test_feed_the_clan_gains_only_the_replacement_amount(ferocious):
    eng=game()
    filler(eng,'Bear',power=4 if ferocious else 3,toughness=5)
    obj=card(eng,'Feed the Clan',zone=Zone.HAND)
    cast(eng,obj)
    assert eng.state.active_player.life==(30 if ferocious else 25)

@pytest.mark.parametrize('name,enabled,expected',(
    ('Grizzly Fate',False,2),('Grizzly Fate',True,4),
    ("Predator's Howl",False,1),("Predator's Howl",True,3)))
def test_token_override_never_creates_base_and_bonus(name,enabled,expected):
    eng=game()
    if enabled:
        if name=='Grizzly Fate':
            for _ in range(7): card(eng,'Forest',zone=Zone.GRAVEYARD)
        else:
            victim=filler(eng,'Victim',power=1,toughness=1)
            eng.rules.destroy(victim)
    obj=card(eng,name,zone=Zone.HAND)
    cast(eng,obj)
    assert len([o for o in eng.state.battlefield if o.is_token])==expected

@pytest.mark.parametrize('landfall',(False,True))
def test_mysteries_of_the_deep_reads_landfall_at_resolution(landfall):
    eng=game();p1=eng.state.active_player
    if landfall:
        main_phase(eng)
        land=card(eng,'Forest',zone=Zone.HAND)
        eng.play_land(p1,land)
    obj=card(eng,'Mysteries of the Deep',zone=Zone.HAND)
    before=len(p1.library)
    cast(eng,obj)
    assert len(p1.library)==before-(3 if landfall else 2)

@pytest.mark.parametrize('coven',(False,True))
def test_ritual_of_hope_replaces_pump(coven):
    eng=game()
    a=filler(eng,'A',power=1,toughness=5)
    filler(eng,'B',power=2 if coven else 1,toughness=5)
    filler(eng,'C',power=3,toughness=5)
    obj=card(eng,'Ritual of Hope',zone=Zone.HAND)
    cast(eng,obj)
    assert (a.power,a.toughness)==((3,6) if coven else (2,6))

@pytest.mark.parametrize('white',(False,True))
def test_ray_of_enfeeblement_branches_on_current_target_color(white):
    eng=game()
    target=card(eng,'Baneslayer Angel' if white else 'Colossal Dreadmaw',player='p2')
    obj=card(eng,'Ray of Enfeeblement',zone=Zone.HAND)
    cast(eng,obj,targets=[target])
    assert (target.power,target.toughness)==((1,1) if white else (2,5))

@pytest.mark.parametrize('red,accept',((False,False),(True,False),(True,True)))
def test_ether_well_declining_optional_replacement_still_puts_target_on_top(red,accept):
    eng=game();p2=eng.state.player_by_id('p2')
    target=card(eng,'Shivan Dragon' if red else 'Colossal Dreadmaw',player='p2')
    obj=card(eng,'Ether Well',zone=Zone.HAND)
    cast(eng,obj,targets=[target])
    if red:
        assert eng.state.pending_choice['kind']=='composite_optional'
        eng.resolve_pending_choice('yes' if accept else 'no')
        eng.resolve_until_stable()
    else:
        assert eng.state.pending_choice is None
    assert target.zone==Zone.LIBRARY
    assert p2.library[0 if accept else -1] is target

@pytest.mark.parametrize('outlaw',(False,True))
def test_take_the_fall_replaces_target_pump_and_still_draws(outlaw):
    eng=game();p1=eng.state.active_player
    if outlaw: filler(eng,'Rogue',type_line='Creature — Rogue',power=2,toughness=2)
    target=filler(eng,'Target',player='p2',power=6,toughness=6)
    obj=card(eng,'Take the Fall',zone=Zone.HAND)
    before=len(p1.library)
    cast(eng,obj,targets=[target])
    assert target.power==(2 if outlaw else 5) and target.toughness==6
    assert len(p1.library)==before-1


def _fire():
    eng=game();main_phase(eng)
    eng.state.active_player.mana_pool.add_many(RICH)
    obj=card(eng,'Fight with Fire',zone=Zone.HAND)
    return eng,obj


def test_kicked_fire_actual_offer_and_unequal_division_clones_independently():
    eng,obj=_fire();p1,p2=eng.state.players
    [action]=[a for a in eng.legal_actions(p1) if a.get('instance_id')==obj.instance_id]
    assert action['locked'] and not action['kicker_variant'].get('locked')
    assert action['kicker_variant']['damage_divisions']==[{'requirement_index':0,'total':10,'min_each':1}]
    eng.cast_spell(p1,obj,kicked=1,targets=[p1,p2],damage_divisions={'0':[7,3]})
    clone=GameEngine(eng.state.clone())
    eng.resolve_until_stable();clone.resolve_until_stable()
    assert [p.life for p in eng.state.players]==[13,17]
    assert [p.life for p in clone.state.players]==[13,17]
    assert 'division' not in obj.spell_effects[0].then_specs[0]['params']

@pytest.mark.parametrize('division', (None,{}, {'0':[5]}, {'0':[0,10]}, {'0':[True,9]}, {'0':[4,5]}, {'0':[5,5],'1':[]}))
def test_kicked_fire_rejects_missing_and_invalid_allocations(division):
    eng,obj=_fire();p1,p2=eng.state.players
    before=p1.mana_pool.total()
    with pytest.raises(ValueError):
        eng.cast_spell(p1,obj,kicked=1,targets=[p1,p2],damage_divisions=division)
    assert obj.zone==Zone.HAND and p1.mana_pool.total()==before


def test_fire_unkicked_target_and_damage_remain_creature_only():
    eng,obj=_fire();p1,p2=eng.state.players
    with pytest.raises(ValueError): eng.cast_spell(p1,obj,targets=[p2])
    target=filler(eng,'Target',power=8,toughness=8)
    eng.cast_spell(p1,obj,targets=[target]);eng.resolve_until_stable()
    assert target.damage_marked==5


def test_fire_zero_targets_and_partial_illegality_keep_announced_damage_shares():
    eng,obj=_fire();p1,p2=eng.state.players
    target=filler(eng,'Target',power=9,toughness=9)
    eng.cast_spell(p1,obj,kicked=1,targets=[target,p2],damage_divisions={'0':[7,3]})
    eng.rules.return_to_hand(target)
    eng.resolve_until_stable()
    assert p2.life==17
    eng,obj=_fire()
    eng.cast_spell(eng.state.active_player,obj,kicked=1,targets=[],damage_divisions={'0':[]})
    eng.resolve_until_stable()
    assert [p.life for p in eng.state.players]==[20,20]

@pytest.mark.parametrize('teamwork',(False,True))
def test_we_say_thee_nay_replaces_counter_unless_payment_amount(teamwork):
    eng=game();main_phase(eng);p1,p2=eng.state.players
    for p in (p1,p2):p.mana_pool.add_many(RICH)
    victim=card(eng,'Lightning Bolt',player='p2',zone=Zone.HAND)
    eng.cast_spell(p2,victim,targets=[p1])
    target=eng.state.stack[-1]
    p2.mana_pool.empty();p2.mana_pool.add_many({'C':3})
    helper=filler(eng,'Helper',power=2,toughness=2)
    obj=card(eng,'We Say Thee Nay!',zone=Zone.HAND)
    action=eng._cast_action(p1,obj,teamwork=teamwork)
    assert action['requires_target'] and action['targets'][0]['kind']=='spell'
    assert any(option.get('instance_id')==victim.instance_id for option in action['targets'][0]['options'])
    from mtg_analyzer.services.game_session import GameSession
    session=GameSession(eng,require_setup=False)
    session.apply_action({'type':'cast_spell','instance_id':obj.instance_id,
        'targets':[{'instance_id':victim.instance_id}], 'teamwork':teamwork,
        'teamwork_choices':[helper.instance_id] if teamwork else None})
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        # Three mana can pay the ordinary tax, but cannot pay the replacement tax.
        assert not teamwork
        eng.resolve_pending_choice('pay');eng.resolve_until_stable()
    assert helper.tapped is teamwork
    assert p1.life==(20 if teamwork else 17)


def test_actual_session_payload_carries_target_groups_and_division():
    from mtg_analyzer.services.game_session import GameSession
    eng,obj=_fire();p1,p2=eng.state.players
    session=GameSession(eng,require_setup=False)
    session.apply_action({'type':'cast_spell','instance_id':obj.instance_id,'kicked':1,
        'target_groups':[[{'player_id':p1.id},{'player_id':p2.id}]],'damage_divisions':{'0':[7,3]}})
    eng.resolve_until_stable()
    assert [p.life for p in eng.state.players]==[13,17]


def test_kicked_condition_announcements_support_min_max_and_negation():
    from mtg_analyzer.game.effect_conditions import announced_state
    eng,obj=_fire()
    obj._modal_announced_kicked=2
    assert announced_state({'kind':'kicked','min':1},obj) is True
    assert announced_state({'kind':'kicked','max':0},obj) is False
    assert announced_state({'kind':'not','condition':{'kind':'kicked','min':2}},obj) is False
    assert announced_state({'kind':'kicked','min':3},obj) is False


def test_division_requirement_index_through_nested_seq_bind_and_announced_branch():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.damage_division import prepare,requirements
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    eng,obj=_fire();p1,p2=eng.state.players
    obj._modal_announced_kicked=1
    effects=build_effects([EffectSpec('seq',{'effects':[
        {'type':'damage','params':{'amount':1,'target_kind':'any'}},
        {'type':'bind','params':{'name':'n','amount':{'kind':'fixed','amount':1},'effects':[
            {'type':'if_else','params':{'condition':{'kind':'kicked','min':1},'then':[
                {'type':'damage','params':{'amount':10,'target_kind':'any','count':10,'optional':True,
                                          'divided':True,'division_required':True}}],
                'else':[{'type':'draw','params':{'count':1}}]}}]}}
    ]})],obj)
    assert requirements(effects)==[{'requirement_index':1,'total':10,'min_each':1}]
    copied=prepare(effects,[p1,p1,p2],[[p1],[p1,p2]],{'1':[7,3]})
    assert requirements(copied)==requirements(effects)
    assert "'division':" not in str(effects[0].inner_specs)


@pytest.mark.parametrize('text',(
    'Target creature and target player each gain 1 life. If you control an outlaw, it gains 2 life instead.',
    'Draw a card. If an opponent would gain life this turn, they gain twice that much life instead.',
    'Target creature gets +1/+1 until end of turn. It gets +2/+2 instead if you smell toast.',
))
def test_ambiguous_or_unknown_override_conditions_fail_closed(text):
    from mtg_analyzer.models.cards.card import Card
    assert not parse_oracle(Card(id='near',name='Near',type_line='Instant',is_instant=True,oracle_text=text)).modeled

@pytest.mark.parametrize('name,expected',(('Arrow Storm',4),('Slaying Fire',4)))
def test_existing_specialized_riders_keep_their_paragraph_boundaries(name,expected):
    eng=game();main_phase(eng);p1,p2=eng.state.players
    obj=card(eng,name,zone=Zone.HAND)
    assert parse_oracle(obj.card).modeled
    p1.mana_pool.add_many({'R':5})
    eng.cast_spell(p1,obj,targets=[p2]);eng.resolve_until_stable()
    assert p2.life==20-expected

@pytest.mark.parametrize('kicked',(0,1))
def test_blood_beckoning_announces_and_returns_the_selected_number(kicked):
    eng=game();main_phase(eng);p1=eng.state.active_player;p1.mana_pool.add_many(RICH)
    a=card(eng,'Grizzly Bears',zone=Zone.GRAVEYARD)
    b=card(eng,'Runeclaw Bear',zone=Zone.GRAVEYARD)
    obj=card(eng,'Blood Beckoning',zone=Zone.HAND)
    eng.cast_spell(p1,obj,kicked=kicked,targets=[a,b] if kicked else [a])
    eng.resolve_until_stable()
    assert a.zone==Zone.HAND and b.zone==(Zone.HAND if kicked else Zone.GRAVEYARD)

@pytest.mark.parametrize('kicked',(0,1))
def test_bloodchiefs_thirst_cast_target_limit_changes_with_announced_kicker(kicked):
    eng=game();main_phase(eng);p1=eng.state.active_player;p1.mana_pool.add_many(RICH)
    target=card(eng,'Colossal Dreadmaw',player='p2')
    obj=card(eng,"Bloodchief's Thirst",zone=Zone.HAND)
    if not kicked:
        with pytest.raises(ValueError): eng.cast_spell(p1,obj,targets=[target])
        assert target.zone==Zone.BATTLEFIELD
    else:
        eng.cast_spell(p1,obj,kicked=1,targets=[target]);eng.resolve_until_stable()
        assert target.zone==Zone.GRAVEYARD


def test_divine_resilience_kicked_can_target_more_than_ten_creatures():
    eng=game();main_phase(eng);p1=eng.state.active_player;p1.mana_pool.add_many(RICH)
    creatures=[filler(eng,f'C{i}',power=2,toughness=2) for i in range(12)]
    obj=card(eng,'Divine Resilience',zone=Zone.HAND)
    [action]=[a for a in eng.legal_actions(p1) if a.get('instance_id')==obj.instance_id]
    req=action['kicker_variant']['targets'][0]
    assert req['any_number'] and req['count_max']==12
    eng.cast_spell(p1,obj,kicked=1,targets=creatures)
    eng.resolve_until_stable()
    assert all('indestructible' in c.temp_keywords for c in creatures)


def test_bare_target_spell_kicked_pronoun_is_not_misread_as_source_choice():
    assert not parse_oracle(_db_card("Ertai's Trickery")).modeled


def test_kicked_fire_rejects_duplicate_targets_and_keeps_exact_mana_cost():
    eng,obj=_fire();p1,p2=eng.state.players
    before=p1.mana_pool.total()
    with pytest.raises(ValueError):
        eng.cast_spell(p1,obj,kicked=1,targets=[p2,p2],damage_divisions={'0':[5,5]})
    assert obj.zone==Zone.HAND
    eng.cast_spell(p1,obj,kicked=1,targets=[p2],damage_divisions={'0':[10]})
    assert p1.mana_pool.total()==before-9


def test_copied_kicked_fire_preserves_allocation_with_targets_replaced():
    eng,obj=_fire();p1,p2=eng.state.players
    eng.cast_spell(p1,obj,kicked=1,targets=[p1,p2],damage_divisions={'0':[7,3]})
    original=eng.state.stack[-1]
    [copy]=eng.rules.copy_spell(original,'p1',new_targets=[p2,p1])
    eng.resolve_until_stable()
    assert [p.life for p in eng.state.players]==[10,10]

@pytest.mark.parametrize('enabled',(False,True))
def test_gained_groundswell_landfall_replaces_both_stat_magnitudes(enabled):
    eng=game();main_phase(eng);p1=eng.state.active_player
    target=filler(eng,'Target',power=2,toughness=2)
    if enabled:
        land=card(eng,'Forest',zone=Zone.HAND);eng.play_land(p1,land)
    obj=card(eng,'Groundswell',zone=Zone.HAND);cast(eng,obj,targets=[target])
    assert (target.power,target.toughness)==((6,6) if enabled else (4,4))

@pytest.mark.parametrize('enabled',(False,True))
def test_gained_gather_the_townsfolk_replaces_token_count_at_low_life(enabled):
    eng=game();eng.state.active_player.life=5 if enabled else 6
    obj=card(eng,'Gather the Townsfolk',zone=Zone.HAND);cast(eng,obj)
    assert len([o for o in eng.state.battlefield if o.is_token])==(5 if enabled else 2)

@pytest.mark.parametrize('enabled',(False,True))
def test_gained_fiery_impulse_spell_mastery_replaces_damage(enabled):
    eng=game()
    if enabled:
        for _ in range(2):card(eng,'Lightning Bolt',zone=Zone.GRAVEYARD)
    target=filler(eng,'Target',power=5,toughness=5)
    obj=card(eng,'Fiery Impulse',zone=Zone.HAND);cast(eng,obj,targets=[target])
    assert target.damage_marked==(3 if enabled else 2)


def test_kicked_etb_uses_original_visit_after_source_is_recast_unkicked():
    eng=game();main_phase(eng);p1=eng.state.active_player;p1.mana_pool.add_many(RICH)
    theirs=filler(eng,'Theirs',player='p2',power=3,toughness=3)
    obj=card(eng,'Desolation Giant',zone=Zone.HAND)
    eng.cast_spell(p1,obj,kicked=1)
    eng.rules.resolve_top_of_stack();eng.rules.put_triggers_on_stack()
    eng.rules.return_to_hand(obj)
    obj.intrinsic_keywords.add('flash')
    eng.cast_spell(p1,obj,kicked=0)
    eng.resolve_until_stable()
    assert theirs.zone==Zone.GRAVEYARD and obj.zone==Zone.GRAVEYARD

@pytest.mark.parametrize('groups', ([], [[],[]], 'bad'))
def test_malformed_division_target_groups_raise_value_error(groups):
    from mtg_analyzer.game.damage_division import prepare
    eng,obj=_fire();obj._modal_announced_kicked=1
    with pytest.raises(ValueError):
        prepare(obj.spell_effects,[],groups,{'0':[]})

@pytest.mark.parametrize('kicked',(0,1))
@pytest.mark.parametrize('name',('Jace Beleren','Colossal Dreadmaw'))
def test_ronas_vortex_preserves_union_target_and_controller_scope(name,kicked):
    eng=game();p2=eng.state.player_by_id('p2')
    target=card(eng,name,player='p2')
    obj=card(eng,"Rona's Vortex",zone=Zone.HAND)
    cast(eng,obj,targets=[target],kicked=kicked)
    assert target.zone==(Zone.LIBRARY if kicked else Zone.HAND)
    if kicked:assert p2.library[0] is target

@pytest.mark.parametrize('white',(False,True))
def test_lightning_dart_damage_object_pronoun_keeps_original_target(white):
    eng=game()
    target=card(eng,'Baneslayer Angel' if white else 'Colossal Dreadmaw',player='p2')
    obj=card(eng,'Lightning Dart',zone=Zone.HAND)
    cast(eng,obj,targets=[target])
    assert target.damage_marked==(4 if white else 1)

@pytest.mark.parametrize('kicked',(0,1))
def test_orims_touch_any_target_alias_keeps_shield_target_and_amount(kicked):
    eng=game();p1,p2=eng.state.players
    obj=card(eng,"Orim's Touch",zone=Zone.HAND)
    cast(eng,obj,targets=[p1],kicked=kicked)
    bolt=card(eng,'Lightning Bolt',player='p2',zone=Zone.HAND)
    cast(eng,bolt,targets=[p1])
    assert p1.life==(20 if kicked else 19)
