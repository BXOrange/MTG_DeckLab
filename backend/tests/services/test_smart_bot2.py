"""General decision contracts; names aren't policy keys.

Synthetic views vary names, resources and style. Real engine tests below keep
policy inputs on the redacted client surface. Private setup is test-only.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from mtg_analyzer.services.bot_policies.smart import SmartBot
from mtg_analyzer.services.bot_policies.smart2 import SmartBot2
from mtg_analyzer.services.smart_bot2.profile import build_profile, roles_for, FAMILY_ROLES, ROLE_PATTERNS
from mtg_analyzer.services.smart_bot2.context import Context
from mtg_analyzer.services.smart_bot2.choices import sacrifice_value
from mtg_analyzer.services.smart_bot2.evaluation import score
from tests.services.test_smart_bot import spell, obj, view
from tests.services.test_bots import bear, land, make_game, keep, drive


def policy(cards=(), commanders=(), archetypes=None, combos=()):
    b = SmartBot2('ann')
    b.strategy = build_profile(list(cards), list(commanders), combos=list(combos), archetypes=archetypes,
                               named_signals=False)
    return b


def object_for(card, iid, **extras):
    return obj(iid, card.name, owner='ann', owner_id='ann', mana_value=card.converted_mana_cost,
               mana_cost=card.mana_cost_string, type_line=card.type_line,
               is_land=card.is_land, is_creature=card.is_creature, power=card.power,
               toughness=card.toughness, **extras)


def offered(iid, **extra):
    return {'type': 'cast_spell', 'instance_id': iid, **extra}


def with_mana(v, mana):
    v['mana_potential'] = {'ann': {'variations': [{'mana': mana}]}}
    return v


@pytest.mark.parametrize('role,text', [
    ('cantrip', 'Draw a card.'), ('flashback', 'Flashback {2}{U}'),
    ('storm', 'Storm'), ('landfall', 'Landfall — Whenever a land enters, draw a card.'),
    ('land-ramp', 'Search your library for a basic land card.'),
    ('land-cycle', 'Basic landcycling {2}'), ('reanimate', 'Return target creature card from your graveyard to the battlefield.'),
    ('counter-synergy', 'Put a +1/+1 counter on target creature.'),
    ('proliferate', 'Proliferate.'), ('poison', 'Toxic 1'),
    ('toughness-combat', 'Each creature you control assigns combat damage equal to its toughness.')])
def test_role_has_positive_and_negative_example(role, text):
    assert role in roles_for(text)
    assert role not in roles_for('A simple creature without abilities.')


def test_every_family_role_has_an_actual_producer():
    assert set().union(*FAMILY_ROLES.values()) <= set(ROLE_PATTERNS)


def test_token_reminder_is_not_source_direct_win_or_drain():
    roles = roles_for('Draw two cards. Create a Wicked Role token attached to target creature. '
                      '(When this Aura is put into a graveyard, each opponent loses 1 life.)')
    assert {'draw', 'tokens'} <= roles
    assert not roles & {'drain', 'alt-win', 'death-payoff'}
    assert 'poison' not in roles_for('Proliferate.')


@pytest.mark.parametrize('tag', ['graveyard', 'sacrifice', 'aristocrats', 'reanimator'])
def test_graveyard_family_maps_explicit_aliases_and_catalogue(tag):
    b = policy(archetypes=[tag])
    assert 'graveyard' in b.strategy.philosophies


def test_same_archetype_has_distinct_style_vectors():
    fast = [bear(f'Body {i}', cmc=1) for i in range(8)]
    reactive = [spell(f'Answer {i}', 'Counter target spell.', '{U}', types='Instant') for i in range(8)]
    a, b = policy(fast, archetypes=['spellslinger']), policy(reactive, archetypes=['spellslinger'])
    assert a.strategy.styles['initiative'] > b.strategy.styles['initiative']
    assert b.strategy.styles['reactivity'] > a.strategy.styles['reactivity']


@pytest.mark.parametrize('names', [('Unknown commander', 'New support'), ('Entirely different', 'Unseen design')])
def test_identity_invariance_for_mechanically_identical_cards(names):
    a = spell(names[0], 'Whenever you cast a noncreature spell, draw a card.', '{2}{U}', 3, 'Creature')
    c = spell(names[1], 'Draw two cards.', '{1}{U}', 2)
    b = policy([c], [a]); v = view(hand=[object_for(a,1), object_for(c,2)])
    result = b.play(v, [offered(1), offered(2)])
    reference_engine = copy.copy(a); reference_engine.name = 'Reference engine'
    reference_draw = copy.copy(c); reference_draw.name = 'Reference draw'
    reference = policy([reference_draw], [reference_engine])
    rv = view(hand=[object_for(reference_engine,1),object_for(reference_draw,2)])
    assert result['instance_id'] == reference.play(rv,[offered(1),offered(2)])['instance_id']


def test_hidden_cards_and_library_order_do_not_change_decision_or_trace_position():
    card = bear(); b = policy([card]); v = view(hand=[object_for(card,1)])
    baseline = b.play(v, [offered(1)])
    position = b.memory['trace']['position']
    changed = copy.deepcopy(v)
    changed['state']['players'][1]['hand'] = [{'name':'Secret Answer', 'instance_id':99}]
    changed['state']['players'][0]['library'] = [{'name':'Wanted card'}]
    assert b.play(changed, [offered(1)]) == baseline
    assert b.memory['trace']['position'] == position


@pytest.mark.parametrize('combo', [False, True])
def test_attack_value_piece_is_not_forbidden_to_attack(combo):
    card = bear('Unknown pirate'); card.oracle_text = 'Whenever this creature deals combat damage to an opponent, draw a card.'
    combos = [{'uses':[{'name':card.name},{'name':'Outlet'}], 'requirements':[], 'produces':['Infinite damage']}] if combo else []
    b = policy([card, spell('Outlet')], combos=combos)
    v = view(board=[object_for(card,1, keywords=['Flying'])])
    action = {'type':'attack','instance_id':1,'legal_defenders':[{'kind':'player','id':'bob'}]}
    assert b.play(v,[action])['instance_ids'] == [1]


def test_toughness_damage_and_poison_are_real_combat_channels():
    wall = bear('Unseen wall', power=0,toughness=13)
    leader = spell('Unseen leader','Each creature you control assigns combat damage equal to its toughness.', types='Creature')
    b = policy([wall, leader]); v = view(board=[object_for(wall,1),object_for(leader,2)])
    v['state']['players'][1]['life']=12
    assert b._attack(v,[{'type':'attack','instance_id':1,'legal_defenders':[{'kind':'player','id':'bob'}]}])
    from mtg_analyzer.services.smart_bot2.combat import hit_value
    ctx = Context(v,'ann',b.strategy)
    infected = object_for(wall,3,keywords=['Infect'])
    assert hit_value(ctx,infected,1,{'life':40,'poison':9}) >= 1000


def test_dangerous_attack_preserves_necessary_body():
    a = bear('Small attacker'); blocker = bear('Large enemy', power=6,toughness=6)
    b = policy([a]); enemy = object_for(blocker,2);enemy['controller_id']='bob'
    v = view(board=[object_for(a,1),enemy]);v['state']['players'][0]['life']=3
    assert b._attack(v,[{'type':'attack','instance_id':1,'legal_defenders':[{'kind':'player','id':'bob'}]}]) is None


@pytest.mark.parametrize('basis', ['power','toughness'])
def test_sacrifice_selects_output_not_lowest_mana_value(basis):
    source = spell('Unseen outlet',f'{{B}}, {{T}}, sacrifice another creature: Draw cards equal to the sacrificed creature\'s {basis}.',types='Creature')
    big = bear('Yield body',power=7,toughness=8); small = bear('Cheap body',cmc=1,power=1,toughness=1)
    b = policy([source,big,small]);v = view(board=[object_for(source,1),object_for(big,2),object_for(small,3)])
    a={'type':'activate_ability','instance_id':1,'description':f'Draw cards equal to the sacrificed creature\'s {basis}.',
       'sacrifice_cost':{'count':1,'options':[{'instance_id':2},{'instance_id':3}]}}
    assert b.play(v,[a])['sacrifice_choice']==2


def test_fair_sacrifice_does_not_wait_for_unassembled_combo():
    source=spell('Outlet','Sacrifice another creature: Draw two cards.',types='Artifact')
    token=bear('Token',power=1,toughness=1)
    b=policy([source,token,spell('Missing')],combos=[{'uses':[{'name':'Outlet'},{'name':'Missing'}]}])
    v=view(board=[object_for(source,1),object_for(token,2,is_token=True)])
    a={'type':'activate_ability','instance_id':1,'description':'Draw two cards.',
       'cost_label':'Sacrifice a creature','sacrifice_cost':{'count':1,'options':[{'instance_id':2}]}}
    assert b.play(v,[a])['sacrifice_choice']==2


def test_polymorph_targets_disposable_input_and_can_reequip():
    transform=spell('Transform','Exile target creature. Reveal cards until you reveal a creature card.')
    big=bear('Precious',power=8,toughness=8); small=bear('Input',power=1,toughness=1)
    b=policy([transform,big,small,bear('Future finisher',power=12,toughness=12)]);v=view(hand=[object_for(transform,1)],board=[object_for(big,2),object_for(small,3,is_token=True)])
    a=offered(1,requires_target=True,targets=[{'count':1,'polarity':'beneficial','options':[{'instance_id':2},{'instance_id':3}]}])
    assert b.play(v,[a])['targets'][0]['instance_id']==3
    equip=spell('Equipment','Equip {1}',types='Artifact'); b=policy([equip,big,small])
    v=view(board=[object_for(equip,1,attached_to=3),object_for(big,2),object_for(small,3)])
    a={'type':'activate_ability','instance_id':1,'attach_kind':'equip','description':'Attach Equipment to target creature you control.',
       'requires_target':True,'targets':[{'count':1,'polarity':'beneficial','options':[{'instance_id':2},{'instance_id':3}]}]}
    assert b.play(v,[a])['targets'][0]['instance_id']==2


def test_counter_waits_for_opponent_and_instant_draw_uses_endstep():
    counter=spell('Permission','Counter target spell.',types='Instant')
    draw=spell('Refill','Draw two cards.',types='Instant')
    b=policy([counter,draw]);v=view(hand=[object_for(counter,1),object_for(draw,2)])
    assert b.play(v,[offered(1)]) is None
    v['state']['active_player_id']='bob';v['state']['current_step']='end'
    assert not b.can_pass_turn(v,[])
    assert b.play(v,[offered(2)])['instance_id']==2


def test_x_variants_preserve_real_response_reserve():
    x=spell('Variable','Draw X cards.','{X}{U}',1)
    c=spell('Answer','Counter target spell.','{1}{U}',2,types='Instant')
    b=policy([x,c],archetypes=['control']);v=with_mana(view(hand=[object_for(x,1),object_for(c,2)]),{'U':2,'C':3})
    variants=b._variants(Context(v,'ann',b.strategy),offered(1,has_x=True,max_x=4),[offered(2)])
    assert {a['x'] for a in variants} >= {0,1,2,4}


def test_parameter_target_groups_and_costs_preserve_distinctness():
    card=spell('Split effect','Target creature gets +1/+1. Target creature gets +1/+1.')
    a,bear2=bear('First'),bear('Second');b=policy([card,a,bear2]);v=view(hand=[object_for(card,1)],board=[object_for(a,2),object_for(bear2,3)])
    a=offered(1,requires_target=True,targets=[{'count':1,'polarity':'beneficial','options':[{'instance_id':2},{'instance_id':3}]},
      {'count':1,'polarity':'beneficial','distinct_from_others':True,'options':[{'instance_id':2},{'instance_id':3}]}])
    result=b._fill_in(v,a)
    assert len(result['target_groups'])==2
    assert result['targets'][0]!=result['targets'][1]


def test_bounded_activation_and_memory_rebuild_restart_undo():
    source=spell('Well','{0}: Draw a card.',types='Artifact')
    b=policy([source]);v=view(board=[object_for(source,1)])
    a={'type':'activate_ability','instance_id':1,'description':'Draw a card.'}
    assert b.play(v,[a])
    assert b.play(v,[a]) is None
    session=make_game();b.prepare(session)
    b.memory['reservation']={'purpose':'test'}
    rebuilt=SmartBot2('ann');rebuilt.prepare(session)
    assert rebuilt.memory['reservation']=={'purpose':'test'}
    session.restart();rebuilt.prepare(session)
    assert rebuilt.memory['reservation']=={}


def test_real_engine_smart2_develops_and_wins_without_named_commander():
    session=make_game(ann_deck=[land(),bear('Independent body',power=5,toughness=5)]*20)
    b=SmartBot2('ann');keep(session,'ann','bob');drive(session,{'ann':b},human_ids=('bob',),limit=3000)
    assert session.engine.state.game_over
    assert session.engine.state.winner_id=='ann'


def test_trace_is_only_returned_to_own_seat():
    session=make_game();b=SmartBot2('ann');b.prepare(session)
    b.memory['trace']={'selected':{'instance_id':123}}
    assert session.view(perspective='ann')['bot_decision']['selected']['instance_id']==123
    assert session.view(perspective='bob')['bot_decision'] is None
    assert session.view()['bot_decision'] is None


@pytest.mark.parametrize('purge_kind',['named','duplicate'])
def test_real_library_win_recipe_uses_mechanics_and_coherent_mana(purge_kind):
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    island=Card(id='island',name='Island',type_line='Basic Land — Island',is_land=True,color_identity={'U'})
    swamp=Card(id='swamp',name='Swamp',type_line='Basic Land — Swamp',is_land=True,color_identity={'B'})
    oracle=spell("Thassa's Oracle", "When Thassa's Oracle enters, look at the top X cards of your library, where X is your devotion to blue. If X is greater than or equal to the number of cards in your library, you win the game.",'{U}{U}',2,'Creature',{'U'})
    oracle.is_creature=True;oracle.power=1;oracle.toughness=3
    purge=spell('Demonic Consultation','Choose a card name. Exile the top six cards of your library, then reveal cards from the top of your library until you reveal the named card. Put that card into your hand and exile all other cards revealed this way.','{B}',1,'Instant',{'B'})
    if purge_kind=='duplicate':
        purge=spell('Tainted Pact','Exile the top card of your library. You may put that card into your hand unless it has the same name as another card exiled this way. Repeat this process until you put a card into your hand or you exile two cards with the same name, whichever comes first.','{1}{B}',2,'Instant',{'B'})
    library=[bear(f'Unique unseen card {i}') for i in range(40)]
    session=make_game(ann_deck=library,bob_deck=[land()]*40)
    session._bot_decklists['ann']={'cards':library+[island,island,swamp,land(),oracle,purge],'commanders':[]}
    keep(session,'ann','bob');state=session.engine.state;ann=state.player_by_id('ann')
    ann.hand.clear()
    for c in (island,island,swamp,land()):
        o=GameObject(c,owner_id='ann',zone=Zone.BATTLEFIELD);bind_from_catalogue(o);state.add_to_battlefield(o)
    for c in (oracle,purge):
        o=GameObject(c,owner_id='ann',zone=Zone.HAND);bind_from_catalogue(o);ann.add_to_zone(o,Zone.HAND)
    b=SmartBot2('ann');drive(session,{'ann':b},human_ids=('bob',),limit=100)
    assert state.game_over,session.move_log
    assert not ann.has_lost
    assert not ann.library
    assert not b._failed


def test_duplicate_library_purge_is_rejected_without_reading_library():
    win=spell('Unknown threshold','When this enters, if X is greater than or equal to the number of cards in your library, you win the game.','{U}{U}',2,'Creature')
    pact=spell('Different purge','Exile the top card of your library. Repeat this process until you put a card into your hand or you exile two cards with the same name.','{1}{B}',2,'Instant')
    basic=land()
    b=policy([win,pact,basic,basic]);v=with_mana(view(hand=[object_for(win,1),object_for(pact,2)]),{'U':2,'B':1,'C':1})
    from mtg_analyzer.services.smart_bot2.recipes import library_ready
    assert not library_ready(Context(v,'ann',b.strategy),offered(1))
    # Once one basic copy is visibly outside, this constraint is satisfied.
    v['state']['battlefield']=[object_for(basic,3)]
    assert library_ready(Context(v,'ann',b.strategy),offered(1))


def test_effective_offered_cost_overrides_large_printed_mana_value():
    card=bear('Discount body',cost='{10}{G}{G}',cmc=12,power=12,toughness=12)
    b=policy([card]);v=view(hand=[object_for(card,1)])
    assert Context(v,'ann',b.strategy).cost(offered(1,effective_cost='{G}{G}'))==2


def test_second_spell_timing_values_targeted_payoff():
    engine=spell('Unknown copier','Whenever you cast your second spell each turn, copy that spell if it targets a permanent or player.',types='Creature')
    small=spell('Enabler','Draw a card.','{U}',1)
    large=spell('Payoff','Target creature gets +5/+5.','{1}{G}',2)
    body=bear();b=policy([engine,small,large,body]);v=with_mana(view(hand=[object_for(small,1),object_for(large,2)],board=[object_for(engine,3),object_for(body,4)]),{'U':1,'G':1,'C':1})
    a=offered(2,requires_target=True,targets=[{'count':1,'polarity':'beneficial','options':[{'instance_id':4}]}])
    v['turn_facts']={'spells_cast':{'ann':1}}
    result=b.play(v,[offered(1),a])
    assert result['instance_id']==2
    assert b.memory['trace']['candidates'][0]['terms']['triggers']>0


def test_new_trace_and_turn_facts_do_not_leak_private_opponent_zones():
    session=make_game();keep(session,'ann','bob')
    v=session.view(perspective='ann')
    assert set(v['turn_facts'])=={'spells_cast','life_gained','life_lost','lands_entered'}
    assert not next(p for p in v['state']['players'] if p['id']=='bob').get('hand')


def test_paired_runner_accounts_for_budgets_and_rejections():
    from mtg_analyzer.services.smart_bot2.benchmark import run_match
    result=run_match([land(),bear()]*10,[],SmartBot2,seed=7,action_budget=30,turn_budget=3)
    assert result['status'] in {'won','lost','draw','turn_budget','action_budget'}
    assert not result['errors']
    assert not result['rejections']


def test_control_permanent_is_not_mistaken_for_counterspell_on_cast():
    source=spell('Unknown guardian','Sacrifice this creature: Counter target spell.','{2}{U}',3,'Creature')
    b=policy([source]);v=view(hand=[object_for(source,1)])
    assert b.play(v,[offered(1)])['instance_id']==1


def test_optional_energy_copy_uses_energy_instead_of_mana():
    source=spell('Unseen maker','You may pay {E}{E}{E}. Create a token that is a copy of target permanent you control.',types='Creature')
    b=policy([source]);v=view(board=[object_for(source,1)])
    v['state']['players'][0]['counters']={'energy':3}
    v['pending_choice']={'kind':'pay_energy_then','source_id':1,'energy_cost':3}
    answers=[{'type':'choose','option_id':'pay'},{'type':'decline'}]
    assert b.answer_choice(v,answers)['option_id']=='pay'
    v['state']['players'][0]['counters']['energy']=2
    assert b.answer_choice(v,answers)['type']=='decline'


def test_scry_retains_useful_cards_and_rejects_excess_land():
    l=land();c=bear();b=policy([l,c])
    v=view(board=[object_for(l,i) for i in range(10,16)])
    v['pending_choice']={'kind':'scry','phase':'away'}
    answers=[{'type':'choose','option_id':'1','name':l.name,'instance_id':1},
             {'type':'choose','option_id':'2','name':c.name,'instance_id':2},{'type':'decline'}]
    assert b.answer_choice(v,answers)['option_id']=='1'
    assert b.answer_choice(v,answers[1:])['type']=='decline'


def test_proliferation_accounts_for_actual_engine_collateral():
    card=spell('Counter action','Proliferate.','{G}',1)
    b=policy([card]);v=view(hand=[object_for(card,1)])
    v['state']['players'][0]['poison']=9
    assert b.play(v,[offered(1)]) is None


def test_resource_untap_operator_detects_positive_net_mana():
    rock=spell('Unknown rock','{T}: Add {C}{C}{C}.\n{3}: Untap Unknown rock.',types='Artifact')
    amp=spell('Unknown amplifier','Whenever you tap a nonland permanent for mana, add one mana of any type that permanent produced.',types='Creature')
    b=policy([rock,amp]);v=view(board=[object_for(rock,1,tapped=True),object_for(amp,2)])
    a={'type':'activate_ability','instance_id':1,'description':'Untap Unknown rock.','cost_label':'{3}'}
    assert b.play(v,[a])
    v['state']['battlefield']=v['state']['battlefield'][:1]
    assert policy([rock]).play(v,[a]) is None


def test_benchmark_controls_shuffle_mulligans_and_allocation_randomness():
    from mtg_analyzer.services.smart_bot2.benchmark import run_match
    deck=[land()]*20+[bear(f'Different body {i}') for i in range(20)]
    a=run_match(deck,[],SmartBot2,seed=42,action_budget=60,turn_budget=3)
    b=run_match(deck,[],SmartBot2,seed=42,action_budget=60,turn_budget=3)
    c=run_match(deck,[],SmartBot2,seed=43,action_budget=60,turn_budget=3)
    assert a['trace_digest']==b['trace_digest']
    assert a['actions']==b['actions']
    assert a['trace_digest']!=c['trace_digest']


def test_real_engine_resource_untap_operator_accumulates_net_mana():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_object import GameObject,Zone
    from mtg_analyzer.services.bots import _one_bot_action,GoldfishBot
    amplifier=spell('Kinnan, Bonder Prodigy','Whenever you tap a nonland permanent for mana, add one mana of any type that permanent produced.','{G}{U}',2,'Creature')
    rock=spell('Basalt Monolith',"Basalt Monolith doesn't untap during your untap step.\n{T}: Add {C}{C}{C}.\n{3}: Untap Basalt Monolith.",'{3}',3,'Artifact')
    session=make_game();keep(session,'ann','bob');state=session.engine.state
    state.player_by_id('ann').hand.clear()
    for card in (amplifier,rock):
        o=GameObject(card,owner_id='ann',zone=Zone.BATTLEFIELD);bind_from_catalogue(o);state.add_to_battlefield(o)
    session._bot_decklists['ann']={'cards':[amplifier,rock]+[land()]*30,'commanders':[]}
    bots={'ann':SmartBot2('ann'),'bob':GoldfishBot('bob')}
    highest=0
    for _ in range(100):
        _one_bot_action(session,bots)
        highest=max(highest,state.player_by_id('ann').mana_pool.total())
        if highest>=3:break
    assert highest>=3,session.move_log


def test_face_down_exile_oracle_text_is_redacted_with_other_identity_fields():
    from mtg_analyzer.models.game.game_object import GameObject,Zone
    card=spell('Hidden card','Draw three cards.')
    session=make_game();obj=GameObject(card,owner_id='ann',zone=Zone.EXILE)
    obj.face_down_in_exile=True;session.engine.state.player_by_id('ann').exile.append(obj)
    own=session.view(perspective='ann')['state']['players'][0]['exile'][-1]
    other=session.view(perspective='bob')['state']['players'][0]['exile'][-1]
    assert own['oracle_text']=='Draw three cards.'
    assert other['oracle_text']==''


def test_grouped_scenario_splits_have_distinct_packages_and_coverage_accounting():
    from scripts.benchmark_smart_bot2 import generated_decks
    decks=list(generated_decks());groups=[d['group'] for d in decks]
    assert len(groups)==len(set(groups))
    assert {d['family'] for d in decks} >= {'aggro','control','combo','stax','alternate-win'}
    splits={s:{c['name'] for d in decks if d['split']==s for c in d['cards'] if not c.get('is_land')}
            for s in ('development','validation','test')}
    assert not splits['development'] & splits['test']
    assert not splits['validation'] & splits['test']


def test_large_equivalent_token_army_is_evaluated_as_a_group():
    token=bear('Token',power=1,toughness=1)
    b=policy([token]);v=view(board=[object_for(token,i,is_token=True) for i in range(1,257)])
    offers=[{'type':'attack','instance_id':i,'legal_defenders':[{'kind':'player','id':'bob'}]} for i in range(1,257)]
    result=b._attack(v,offers)
    assert len(result['instance_ids'])==256


def test_unconditional_win_is_an_executable_goal_not_expensive_filler():
    win=spell('Unknown conclusion','You win the game.','{8}{U}{U}',10)
    body=bear();b=policy([win,body]);v=view(hand=[object_for(win,1),object_for(body,2)])
    assert b.play(v,[offered(1),offered(2)])['instance_id']==1
    assert b.memory['trace']['candidates'][0]['plan_status']=='startable'


def test_draw_does_not_destroy_a_visible_exact_hand_win_goal():
    goal=spell('Unknown keeper','At the beginning of your upkeep, if you have exactly 5 cards in your hand, you win the game.',types='Creature')
    draw=spell('Optional refill','Draw two cards.','{U}',1)
    b=policy([goal,draw]);v=view(hand=[object_for(draw,1)]+[{'instance_id':i} for i in range(10,14)],board=[object_for(goal,2)])
    assert b.play(v,[offered(1)]) is None


def test_counter_target_prefers_visible_progress_toward_alternative_win():
    goal=spell('Counter goal','When Counter goal has twenty or more charge counters on it, you win the game.',types='Artifact')
    add=spell('Counter supply','Put a charge counter on target artifact.')
    b=policy([goal,add]);v=view(hand=[object_for(add,1)],board=[object_for(goal,2,counters={'charge':19}),object_for(goal,3,counters={'charge':1})])
    a=offered(1,requires_target=True,targets=[{'count':1,'polarity':'beneficial','options':[{'instance_id':3},{'instance_id':2}]}])
    assert b.play(v,[a])['targets'][0]['instance_id']==2


def test_control_reserves_permission_against_minor_threat_but_answers_large_one():
    counter=spell('Reactive permission','Counter target spell.','{U}{U}',2,'Instant')
    b=policy([counter],archetypes=['control'])
    v=view(hand=[object_for(counter,1)],stack=[{'stack_id':1,'controller_id':'bob','object':{'instance_id':10,'name':'Small threat','power':1,'toughness':1,'mana_value':1}}])
    a=offered(1,requires_target=True,targets=[{'count':1,'polarity':'harmful','options':[{'stack_id':1}]}])
    assert b.play(v,[a]) is None
    v['state']['stack'][0]['object'].update(power=6,toughness=6,mana_value=6)
    assert b.play(v,[a])['instance_id']==1


def test_different_faces_are_evaluated_as_different_effects_without_mutating_source():
    from mtg_analyzer.models.cards.card import Card
    card=Card(id='two-faces',name='Slow Front // Fast Back',type_line='Creature',is_creature=True,
              mana_cost_string='{5}{G}',converted_mana_cost=6,power=2,toughness=2,layout='modal_dfc',
              oracle_text='Vigilance',back_name='Fast Back',back_type_line='Sorcery',
              back_mana_cost_string='{U}',back_oracle_text='Draw two cards.')
    b=policy([card]);v=view(hand=[object_for(card,1)])
    action=offered(1,face='back',name='Fast Back',effective_cost='{U}')
    ctx=Context(v,'ann',b.strategy)
    assert ctx.plan(action).types=='sorcery'
    assert 'draw' in ctx.roles(action)
    assert b.play(v,[offered(1,effective_cost='{5}{G}'),action])['face']=='back'
    assert v['state']['players'][0]['hand'][0]['name']==card.name


@pytest.mark.parametrize('cost,devotion,library,cast',[('{G}{G}{G}','green',3,True),('{G}','green',2,False),('{U}{U}','blue',2,True)])
def test_library_threshold_is_mechanic_based_not_an_oracle_two_card_constant(cost,devotion,library,cast):
    card=spell('Unseen prophet',f'When Unseen prophet enters, if X is greater than or equal to the number of cards in your library, you win the game, where X is your devotion to {devotion}.',cost,3,'Creature')
    b=policy([card]);v=view(hand=[object_for(card,1)]);v['state']['players'][0]['library_count']=library
    assert bool(b.play(v,[offered(1)]))==cast


def test_style_density_is_invariant_under_functionally_identical_reprints():
    source=spell('One repeated source','{T}: Add {G}.',types='Artifact')
    bodies=[bear(f'Other body {i}') for i in range(31)]
    repeated=policy([source]*9+bodies)
    distinct=policy([spell(f'Equivalent source {i}',source.oracle_text,types='Artifact') for i in range(9)]+bodies)
    assert repeated.strategy.styles==distinct.strategy.styles


@pytest.mark.parametrize('subtype',['Elf','Goblin'])
def test_typal_payoff_follows_affected_board_not_named_lord_or_archetype(subtype):
    lord=spell('Unknown lord',f'Other {subtype} creatures you control get +1/+1.','{1}{G}{G}',3,'Creature')
    filler=bear('Unrelated body',cmc=1)
    tribe=bear('Member');tribe.type_line=f'Creature — {subtype}'
    b=policy([lord,filler,tribe],archetypes=['control'])
    v=view(hand=[object_for(lord,1),object_for(filler,2)],board=[object_for(tribe,i) for i in range(10,16)])
    assert b.play(v,[offered(1),offered(2)])['instance_id']==1
    for o in v['state']['battlefield']:o['type_line']='Creature — Other'
    assert b.play(v,[offered(1),offered(2)])['instance_id']==2


def test_production_policy_modules_do_not_import_or_read_live_engine_state():
    import ast
    from pathlib import Path
    import mtg_analyzer.services.smart_bot2 as package
    paths=list(Path(package.__file__).parent.glob('*.py'))
    paths.append(Path(__import__('mtg_analyzer.services.bot_policies.smart2',fromlist=['__file__']).__file__))
    for path in paths:
        if path.name=='benchmark.py':continue  # privileged fixture/measurement boundary
        tree=ast.parse(path.read_text())
        assert not any(isinstance(n,ast.Attribute) and n.attr=='engine'
                       and not (isinstance(n.value,ast.Name) and n.value.id=='W')
                       for n in ast.walk(tree)),path  # W.engine is a utility coefficient
        assert not any(isinstance(n,ast.ImportFrom) and n.module and '.game.' in n.module for n in ast.walk(tree)),path


def test_smart2_snapshot_matcher_is_offline_and_preserves_snapshot(monkeypatch,tmp_path):
    import hashlib
    from mtg_analyzer.services import commander_spellbook_database as module
    from mtg_analyzer import config
    from tests.services.test_commander_spellbook_database import _variant,_write_snapshot
    path=tmp_path/'combos.db';db=module.CommanderSpellbookDatabase(path)
    snapshot=_write_snapshot(tmp_path/'snapshot.gz',[_variant('line',[('Engine',1),('Outlet',1)],produces=['Infinite damage'])])
    db.ingest_snapshot(snapshot);db.close()
    monkeypatch.setattr(config,'COMMANDER_SPELLBOOK_DB_PATH',path)
    monkeypatch.setattr(module.CommanderSpellbookDatabase,'_refresh',lambda self:pytest.fail('network'))
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    p=build_profile([spell('Engine'),spell('Outlet')],[])
    assert len(p.combos)==1
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


def test_rewind_and_takeback_invalidate_smart2_timeline_memory():
    from mtg_analyzer.services.game_session import GameSessionManager
    session=GameSessionManager().create_multiplayer([
        {'player_id':'ann','library':[land()]*30},{'player_id':'bob','library':[land()]*30}],
        mulligan_style='none',takebacks_per_player=1)
    keep(session,'ann','bob');b=SmartBot2('ann');b.prepare(session)
    session.apply_action({'type':'pass_priority'},actor_id='ann')
    b.memory['reservation']={'purpose':'obsolete'}
    session.rewind();b.prepare(session)
    assert b.memory['reservation']=={}
    session.apply_action({'type':'pass_priority'},actor_id='ann')
    b.memory['reservation']={'purpose':'obsolete'}
    session.take_back('ann');b.prepare(session)
    assert b.memory['reservation']=={}


def test_real_multiplayer_smart2_wins_against_two_separate_opponents():
    from mtg_analyzer.services.game_session import GameSessionManager
    from mtg_analyzer.services.bots import GoldfishBot,run_bots
    deck=[land(),bear('Unknown finisher',power=7,toughness=7)]*25
    session=GameSessionManager().create_multiplayer([
        {'player_id':'ann','library':deck},
        {'player_id':'bob','library':[land()]*50},
        {'player_id':'cy','library':[land()]*50}],mulligan_style='none')
    session._keep_history=False
    bots={'ann':SmartBot2('ann'),'bob':GoldfishBot('bob'),'cy':GoldfishBot('cy')}
    for _ in range(20):
        run_bots(session,bots,max_actions=200)
        if session.engine.state.game_over:break
    assert session.engine.state.game_over
    assert session.engine.state.winner_id=='ann'
    assert not bots['ann']._failed


@pytest.mark.parametrize('kind,good_owner,text', [
    ('+1/+1','ann',''), ('loyalty','ann',''), ('shield','ann',''),
    ('-1/-1','bob',''), ('stun','bob',''), ('age','bob','Cumulative upkeep {1}.'),
    ('charge','ann','Remove a charge counter: Draw a card.'),
    ('oil','ann','Remove an oil counter: Add {G}.'),
    ('quest','ann','Remove three quest counters: Draw a card.'),
    ('time','ann','Vanishing 3'), ('time','bob','When the last time counter is removed, sacrifice it and draw three cards.'),
    ('ice','bob','When this permanent has no ice counters on it, sacrifice it and create a token.'),
])
@pytest.mark.parametrize('bot_type',[SmartBot,SmartBot2])
def test_smart_proliferation_chooses_beneficial_owner_without_card_names(kind,good_owner,text,bot_type):
    b=policy() if bot_type is SmartBot2 else SmartBot('ann')
    board=[obj(i, 'Unknown '+str(i), owner=owner, counters={kind:1}, oracle_text=text)
           for i,owner in [(1,'ann'),(2,'bob')]]
    v=view(board=board)
    v['pending_choice']={'kind':'proliferate','options':[
        {'id':'object:'+str(i),'instance_id':i} for i in (1,2)]}
    answers=[{'type':'choose','option_id':'object:'+str(i),'instance_id':i} for i in (1,2)]+[{'type':'decline'}]
    assert b.answer_choice(v,answers)['instance_id']==(1 if good_owner=='ann' else 2)
    bad=2 if good_owner=='ann' else 1
    assert b.answer_choice(v,[answers[bad-1],answers[-1]])['type']=='decline'


def test_proliferation_skips_neutral_unknown_and_mixed_collateral_but_takes_lethal_poison():
    b=policy();v=view(board=[obj(1,'A',owner='ann',counters={'+1/+1':1,'stun':1}),
                            obj(2,'B',owner='ann',counters={'flying':1,'finality':1,'unknown':7})])
    v['state']['players'][0].update(poison=9,counters={'energy':1})
    v['state']['players'][1].update(poison=9,counters={'energy':1})
    v['pending_choice']={'kind':'proliferate','options':[
        {'id':'object:1','instance_id':1},{'id':'object:2','instance_id':2},
        {'id':'player:ann','player_id':'ann'},{'id':'player:bob','player_id':'bob'}]}
    answers=[{'type':'choose','option_id':o['id'],'instance_id':o.get('instance_id')} for o in v['pending_choice']['options']]+[{'type':'decline'}]
    assert b.answer_choice(v,answers)['option_id']=='player:bob'
    assert b.answer_choice(v,answers[:3]+answers[-1:])['type']=='decline'


@pytest.mark.parametrize('kind', ['energy','experience','poison','rad'])
def test_proliferate_player_resources_and_harm(kind):
    b=policy();v=view()
    for p in v['state']['players']:
        p['counters']={kind:1}
    v['pending_choice']={'kind':'proliferate','options':[{'id':'p:'+p['id'],'player_id':p['id']} for p in v['state']['players']]}
    answers=[{'type':'choose','option_id':o['id']} for o in v['pending_choice']['options']]+[{'type':'decline'}]
    assert b.answer_choice(v,answers)['option_id']=='p:'+('ann' if kind in ('energy','experience') else 'bob')


def test_proliferate_cast_uses_selectable_gain_instead_of_enemy_planeswalker_collateral():
    c=spell('Any proliferator','Proliferate.','{G}',1)
    b=policy([c]);v=view(hand=[object_for(c,1)],board=[obj(2,'Walker',owner='bob',counters={'loyalty':10}),
                                                                  obj(3,'Mine',owner='ann',counters={'+1/+1':1})])
    v['state']['players'][0]['poison']=9
    assert b.play(v,[offered(1)])
    ctx=Context(v,'ann',b.strategy)
    assert score(ctx,offered(1))[1]['counter_delta']>0
    v['state']['battlefield']=v['state']['battlefield'][:1]
    assert b.play(v,[offered(1)]) is None


def test_proliferation_uses_battle_protector_and_avoids_sagas_final_chapter():
    from mtg_analyzer.services.smart_bot2.counters import recipient_value
    v=view(board=[obj(1,'Battle',owner='ann',type_line='Battle — Siege',
                      counters={'defense':2},protector_id='bob'),
                  obj(2,'Saga',owner='ann',type_line='Enchantment — Saga',counters={'lore':1},
                      oracle_text='I, II — Draw a card.\nIII — Create a token.')])
    ctx=Context(v,'ann',policy().strategy)
    assert recipient_value(ctx,ctx.obj({'instance_id':1}))<0
    v['state']['battlefield'][0]['protector_id']='ann'
    assert recipient_value(ctx,ctx.obj({'instance_id':1}))>0
    assert recipient_value(ctx,ctx.obj({'instance_id':2}))>0
    v['state']['battlefield'][1]['counters']['lore']=2
    assert recipient_value(ctx,ctx.obj({'instance_id':2}))==0


def test_proliferation_unknown_named_resources_require_printed_use():
    from mtg_analyzer.services.smart_bot2.counters import recipient_value
    v=view(board=[obj(1,'Unfamiliar marker',owner='ann',counters={'charge':1})])
    ctx=Context(v,'ann',policy().strategy)
    assert recipient_value(ctx,ctx.obj({'instance_id':1}))==0
    v['state']['battlefield'][0]['oracle_text']='Remove a charge counter: Draw a card.'
    assert recipient_value(ctx,ctx.obj({'instance_id':1}))>0


def test_mixed_opposing_pt_counters_do_not_invent_lethal_damage():
    from mtg_analyzer.services.smart_bot2.counters import recipient_value
    v=view(board=[obj(1,'Enemy',owner='bob',toughness=1,counters={'+1/+1':1,'-1/-1':1})])
    ctx=Context(v,'ann',policy().strategy)
    assert recipient_value(ctx,ctx.obj({'instance_id':1}))==0


def test_proliferation_recognizes_generic_immediate_counter_win_threshold():
    c=spell('Expensive proliferation','Proliferate.','{6}',6)
    b=policy([c]);v=view(hand=[object_for(c,1)],board=[obj(2,'Unfamiliar apparatus',owner='ann',
        type_line='Artifact',counters={'charge':19},
        oracle_text='When this artifact has twenty or more charge counters on it, you win the game.')])
    assert b.play(v,[offered(1)])
    v['state']['battlefield'][0]['counters']['charge']=1
    assert b.play(v,[offered(1)]) is None



def test_smart2_keeps_windows_only_while_it_can_pay_for_them():
    from mtg_analyzer.services.bot_policies.smart2 import SmartBot2
    from tests.services.test_smart_bot import view, obj
    b = SmartBot2('ann')
    v = view(hand=[obj(1, 'Shock', type_line='Instant', oracle_text='deal 2 damage', castable=False)])
    v['priority'] = {'interactive': True, 'yields': {}, 'stops': {'ann': {}}}
    pass_only = [{'type': 'pass_priority'}]
    assert b.can_pass_turn(v, pass_only)  # instant, but no mana for it
    v['state']['players'][0]['hand'][0]['castable'] = True
    assert not b.can_pass_turn(v, pass_only)  # affordable instant
    v['state']['players'][0]['hand'] = []
    assert not b.can_pass_turn(v, pass_only + [{'type': 'activate_ability', 'instance_id': 2}])
    assert b.can_pass_turn(v, pass_only)  # lands/rocks only offer tap_for_mana


def test_attacks_own_battle_but_not_an_opponents():
    # RULE 310.8b: the Siege's controller attacks it; report 20261022T213932 (battle never attacked).
    a = bear('Raider')
    b = policy([a])
    siege = lambda iid, owner: obj(iid, 'Siege', owner=owner, is_battle=True, protector_id='bob', defense=5)
    defender = {'kind': 'battle', 'instance_id': 7}
    offer = [{'type': 'attack', 'instance_id': 1, 'legal_defenders': [defender]}]
    v = view(board=[object_for(a, 1), siege(7, 'ann')])
    assert b._attack(v, offer) == {'type': 'attack', 'instance_ids': [1], 'defender': defender}
    v = view(board=[object_for(a, 1), siege(7, 'cy')])
    assert b._attack(v, offer) is None
