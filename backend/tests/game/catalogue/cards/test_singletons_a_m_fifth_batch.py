"""Singleton Battles cover their front and back abilities, including hidden choices."""
import pytest
from mtg_analyzer.game.binding.core import bind_from_catalogue,build_effects
from mtg_analyzer.game.card_registry import _REGISTRY,specs_for
from mtg_analyzer.game.effects.core import GameContext,_apply_effects_partitioned
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards import card_query
from mtg_analyzer.models.game.game_object import GameObject,Zone
from mtg_analyzer.models.game.events import EventType,GameEvent
from tests.support.catalogue import battlefield_object,two_player_game


def put(engine,p,name,typ='Creature',**kw):
    obj=battlefield_object(engine,p,name,typ,**kw);bind_from_catalogue(obj);obj.summoning_sick=False
    return obj


def card_in(engine,p,name,zone=Zone.GRAVEYARD,typ='Creature',**kw):
    obj=GameObject(Card(id=name,name=name,type_line=typ,**kw),owner_id=p,zone=zone)
    engine.state.player_by_id(p).add_to_zone(obj,zone);bind_from_catalogue(obj)
    return obj


def run(engine,source,index=0,targets=None):
    _apply_effects_partitioned(build_effects(_REGISTRY[source.name.lower()]()[index].effects,source),GameContext(engine.state,engine.rules),targets,None,source=source)


def target_ids(engine,source):
    effect=build_effects(_REGISTRY[source.name.lower()]()[0].effects,source)[0]
    return {o.get('instance_id') for o in legal_targets(engine.state,source.controller_id,effect.target_spec,source)}


def etb(engine,source):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=source.instance_id,controller_id=source.controller_id,object_types=sorted(source.type_words)))
    engine.resolve_until_stable()


def test_matzalantli_counts_permanent_types_not_kindred_or_instant_and_transforms():
    engine,p=two_player_game()
    c=Card(id='matz',name='Matzalantli, the Great Door // The Core',type_line='Legendary Artifact',layout='transform',back_name='The Core',back_type_line='Legendary Land',back_oracle_text='Fathomless descent — {T}: Add X mana of any one color, where X is the number of permanent cards in your graveyard.')
    source=GameObject(c,owner_id=p.id,zone=Zone.BATTLEFIELD);engine.state.add_to_battlefield(source);bind_from_catalogue(source);source.summoning_sick=False
    card_in(engine,p.id,'Two types',typ='Artifact Creature',is_creature=True)
    card_in(engine,p.id,'Kindred Instant',typ='Kindred Instant — Elf',is_instant=True)
    card_in(engine,p.id,'Enchantment',typ='Enchantment')
    p.mana_pool.add('C',4)
    with pytest.raises(ValueError):engine.activate_ability(p,source,1)
    card_in(engine,p.id,'Land',typ='Land',is_land=True)
    engine.activate_ability(p,source,1);engine.resolve_until_stable()
    assert source.transformed and source.name=='The Core' and source.is_land
    source.tapped=False
    made=engine.tap_for_mana(p,source,option_index=0)
    assert sum(made.values())==3  # three permanent cards, despite four permanent types


def test_matzalantli_keeps_its_loot_ability():
    engine,p=two_player_game();source=put(engine,p.id,'Matzalantli, the Great Door','Artifact')
    drawn=card_in(engine,p.id,'Drawn',Zone.LIBRARY)
    engine.activate_ability(p,source,0);engine.resolve_until_stable()
    if engine.state.pending_choice:
        option=next(o for o in engine.state.pending_choice['options'] if o.get('instance_id')==drawn.instance_id)
        engine.resolve_pending_choice(option['id']);engine.resolve_until_stable()
    assert drawn.zone==Zone.GRAVEYARD


def test_lorwyn_targets_only_enemy_nonelf_with_power_within_land_count():
    engine,p=two_player_game();siege=put(engine,p.id,'Invasion of Lorwyn','Battle — Siege',defense=4)
    lands=[put(engine,p.id,f'Land{i}','Land',is_land=True) for i in range(2)]
    yes=put(engine,'p2','Bear',is_creature=True,power=2,toughness=2)
    big=put(engine,'p2','Big',is_creature=True,power=3,toughness=3)
    elf=put(engine,'p2','Elf','Creature — Elf',is_creature=True,power=1,toughness=1)
    own=put(engine,p.id,'Own',is_creature=True,power=1,toughness=1)
    assert target_ids(engine,siege)=={yes.instance_id}
    etb(engine,siege);engine.resolve_pending_choice(str(yes.instance_id));engine.resolve_until_stable()
    assert yes.zone==Zone.GRAVEYARD and big.zone==elf.zone==own.zone==Zone.BATTLEFIELD


def test_lorwyn_rechecks_live_land_count_on_resolution():
    engine,p=two_player_game();siege=put(engine,p.id,'Invasion of Lorwyn','Battle — Siege',defense=4)
    land1=put(engine,p.id,'Land1','Land',is_land=True);put(engine,p.id,'Land2','Land',is_land=True)
    target=put(engine,'p2','Bear',is_creature=True,power=2,toughness=2)
    etb(engine,siege);engine.rules.resolve_choice(str(target.instance_id))
    engine.rules.exile(land1);engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD


def test_ravnica_excludes_exactly_two_colors_lands_and_your_permanents():
    engine,p=two_player_game();siege=put(engine,p.id,'Invasion of Ravnica','Battle — Siege',defense=4)
    targets=[put(engine,'p2',f'Colors{i}','Artifact',color_identity=set('WUG'[:i])) for i in range(4)]
    land=put(engine,'p2','Land','Land',is_land=True);own=put(engine,p.id,'Own','Artifact')
    enemy_battle=put(engine,'p2','Enemy battle','Battle — Siege',defense=4)
    put(engine,'p2','Land Creature','Land Creature — Dryad',is_land=True,is_creature=True,power=1,toughness=1,color_identity={'G'})
    put(engine,'p2','Artifact Land','Artifact Land',is_land=True)
    assert target_ids(engine,siege)=={targets[i].instance_id for i in (0,1,3)} | {enemy_battle.instance_id}
    etb(engine,siege);engine.resolve_pending_choice(str(targets[3].instance_id));engine.resolve_until_stable()
    assert targets[3].zone==Zone.EXILE and targets[2].zone==Zone.BATTLEFIELD


def test_guildpact_paragon_looks_privately_and_reveals_only_selected_two_color_card():
    engine,p=two_player_game();engine.state.current_step='main1'
    source=put(engine,p.id,'Guildpact Paragon',is_creature=True,power=5,toughness=5)
    looked=[card_in(engine,p.id,f'Look{i}',Zone.LIBRARY,typ='Sorcery',is_sorcery=True,mana_cost_string=('{W}{U}' if i==2 else '{G}')) for i in range(6)]
    mono=card_in(engine,p.id,'Mono',Zone.HAND,typ='Instant',is_instant=True,mana_cost_string='{G}')
    p.mana_pool.add('G',1);engine.cast_spell(p,mono);engine.resolve_until_stable()
    assert not engine.state.pending_choice
    spell=card_in(engine,p.id,'Two color spell',Zone.HAND,typ='Instant',is_instant=True,mana_cost_string='{W}{G}')
    p.mana_pool.add_many({'W':1,'G':1});engine.cast_spell(p,spell);engine.resolve_until_stable()
    assert not [e for e in engine.state.event_log if e.type==EventType.REVEAL]
    choice=engine.state.pending_choice
    candidates=[o for o in choice['options'] if o.get('instance_id')]
    assert {o['instance_id'] for o in candidates}=={looked[2].instance_id}
    engine.resolve_pending_choice(candidates[0]['id']);engine.resolve_until_stable()
    reveals=[e for e in engine.state.event_log if e.type==EventType.REVEAL]
    assert len(reveals)==1 and reveals[0].get('instance_id')==looked[2].instance_id
    assert looked[2] in p.hand and len(p.library)==5


def test_tolvada_reanimates_permanent_but_never_battle_or_instant_or_enemy_graveyard():
    engine,p=two_player_game();siege=put(engine,p.id,'Invasion of Tolvada','Battle — Siege',defense=4)
    bear=card_in(engine,p.id,'Bear',is_creature=True,power=2,toughness=2)
    battle=card_in(engine,p.id,'Battle',typ='Battle — Siege',defense=4)
    spell=card_in(engine,p.id,'Instant',typ='Instant',is_instant=True)
    enemy=card_in(engine,'p2','Enemy',is_creature=True,power=2,toughness=2)
    assert target_ids(engine,siege)=={bear.instance_id}
    etb(engine,siege);engine.resolve_pending_choice(str(bear.instance_id));engine.resolve_until_stable()
    assert bear.zone==Zone.BATTLEFIELD and battle.zone==spell.zone==enemy.zone==Zone.GRAVEYARD


@pytest.mark.parametrize('typ,layout,draws', [('Land','',True),('Creature','transform',True),('Creature','modal_dfc',True),('Creature','meld',True),('Creature','flip',False),('Creature','split',False),('Creature','',False)])
def test_pyrulea_scry_then_reveal_draws_only_land_or_double_faced(typ,layout,draws):
    engine,p=two_player_game();siege=put(engine,p.id,'Invasion of Pyrulea','Battle — Siege',defense=4)
    top=card_in(engine,p.id,'Top',Zone.LIBRARY,typ=typ,layout=layout,is_land=typ=='Land')
    run(engine,siege)
    while engine.state.pending_choice:
        choice=engine.state.pending_choice
        options=choice['options']
        keep=next((o for o in options if o['id'] in ('top','keep')),None)
        engine.resolve_pending_choice((keep or options[0])['id'])
    engine.resolve_until_stable()
    assert (top in p.hand) is draws
    reveals=[e for e in engine.state.event_log if e.type==EventType.REVEAL]
    assert len(reveals)==1 and reveals[0].get('instance_id')==top.instance_id


def test_slabhorn_grants_only_other_transformed_permanents_trample_and_ward():
    engine,p=two_player_game();source=put(engine,p.id,'Gargantuan Slabhorn',is_creature=True,power=4,toughness=4)
    source.transformed=True
    eligible=put(engine,p.id,'Transformed',is_creature=True,power=2,toughness=2);eligible.transformed=True
    normal=put(engine,p.id,'Normal',is_creature=True,power=2,toughness=2)
    enemy=put(engine,'p2','Enemy',is_creature=True,power=2,toughness=2);enemy.transformed=True
    engine.recompute_continuous_effects()
    assert 'trample' in eligible.granted_keywords and eligible.granted_ward_cost=='{2}'
    assert all('trample' not in o.granted_keywords and not o.granted_ward_cost for o in (source,normal,enemy))


@pytest.mark.parametrize('name',['Matzalantli, the Great Door','Invasion of Lorwyn','Invasion of Ravnica','Guildpact Paragon','Invasion of Tolvada','Invasion of Pyrulea','Gargantuan Slabhorn'])
def test_authored_specs_fresh_and_bind(name):
    c=Card(id=name,name=name,type_line='Artifact');a,b=specs_for(c),specs_for(c)
    assert a and all(x is not y for x,y in zip(a,b))
    obj=GameObject(c,owner_id='p1',zone=Zone.BATTLEFIELD);bind_from_catalogue(obj)
    assert obj.triggered_abilities or obj.activated_abilities or obj.static_effects


@pytest.mark.parametrize('layout,expected',[('transform',True),('modal_dfc',True),('meld',True),('flip',False),('split',False),('adventure',False)])
def test_double_faced_criteria_uses_layout_not_image_or_two_names(layout,expected):
    c=Card(id='test',name='Test',type_line='Creature',layout=layout)
    assert card_query.matches(c,{'double_faced':True}) is expected


def test_gargantuan_slabhorn_preserves_printed_trample_and_ward():
    engine,p=two_player_game()
    source=put(engine,p.id,'Gargantuan Slabhorn',is_creature=True,power=4,toughness=4,
               oracle_text='Trample, ward {2}\nOther transformed permanents you control have trample and ward {2}.',
               keywords=['Trample','Ward'])
    engine.recompute_continuous_effects()
    assert 'trample' in source.intrinsic_keywords and source.parametric_keywords['ward']['cost']=='{2}'


def test_ravnica_rechecks_color_count_after_target_announcement():
    engine,p=two_player_game();siege=put(engine,p.id,'Invasion of Ravnica','Battle — Siege',defense=4)
    target=put(engine,'p2','Initially monocolored','Artifact',color_identity={'W'})
    etb(engine,siege);engine.rules.resolve_choice(str(target.instance_id))
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    effects=build_effects([EffectSpec('grant_until',{'static':{'type':'color_change','params':{'colors':['W','U'],'set':True}},'target_kind':'permanent','duration':'end_of_turn'})],siege)
    effects[0].apply(GameContext(engine.state,engine.rules),[target])
    engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD


def test_two_color_card_criteria_counts_actual_colors_not_commander_identity():
    c=Card(id='test',name='Test',type_line='Creature',mana_cost_string='{W}{U}',color_identity={'W','U','G'})
    assert card_query.matches(c,{'color_count':2})
    assert not card_query.matches(c,{'color_count':3})


def test_lorwyn_backface_tracks_its_controllers_lands():
    engine,p=two_player_game()
    source=put(engine,p.id,'Winnowing Forces',is_creature=True,power=0,toughness=0,
               oracle_text="Winnowing Forces's power and toughness are each equal to the number of lands you control.")
    for i in range(3):put(engine,p.id,f'Land{i}','Land',is_land=True)
    engine.recompute_continuous_effects()
    assert (source.power,source.toughness)==(3,3)


def test_tolvada_backface_creates_spirit_and_buffs_tokens_with_lifelink():
    engine,p=two_player_game()
    source=put(engine,p.id,'The Broken Sky','Enchantment',oracle_text='Creature tokens you control get +1/+0 and have lifelink.\nAt the beginning of your end step, create a 1/1 white and black Spirit creature token with flying.')
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='end',player_id=p.id));engine.resolve_until_stable()
    tokens=[o for o in engine.state.battlefield if o.is_token]
    assert len(tokens)==1 and (tokens[0].power,tokens[0].toughness)==(2,1)
    assert 'lifelink' in tokens[0].granted_keywords
