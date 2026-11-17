"""PAR-320 residue: exercise real cards through the stack and resumable choices."""
import pytest

from test_par320_edict_counts_punishers import _three, _put, _real, _card, _creature, _land, _upkeep
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle.gate import parse_oracle

RESIDUE = ('Death Cloud','Pox','Pox Plague','Fraying Omnipotence','Devastating Dreams','Choice of Damnations',
    'By Invitation Only','Curse of the Cabal','Meathook Massacre II','Possessed Portal',"Vona's Hunger",'Tectonic Split',
    "Braids's Frightful Return",'Rakdos, Patron of Chaos','Invoke Despair','Infernal Denizen','Xathrid Demon',
    'Devouring Sugarmaw','Gargantuan Gorilla','Lich')


def _hand(eng, pid, count):
    p = eng.state.player_by_id(pid)
    p.hand.extend(GameObject(_card(f'H{pid}{i}', type_line='Sorcery'), owner_id=pid, zone=Zone.HAND) for i in range(count))


def _library(eng, pid, count=10):
    p = eng.state.player_by_id(pid)
    p.library.extend(GameObject(_card(f'L{pid}{i}', type_line='Sorcery'), owner_id=pid, zone=Zone.LIBRARY) for i in range(count))


def _spell(eng, name, targets=None, x=0):
    obj=GameObject(_real(name), owner_id='p1', zone=Zone.STACK)
    obj.controller_id='p1'; obj.x_paid=x
    bind_from_catalogue(obj)
    eng.state.stack.append(StackItem('spell','p1', obj=obj, effects=getattr(obj,"spell_effects",[]), targets=targets, x=x))
    eng.resolve_until_stable()
    return obj


def _answer(eng, value):
    eng.resolve_pending_choice(str(value));eng.resolve_until_stable()


def _finish(eng):
    for _ in range(100):
        choice=eng.state.pending_choice
        if not choice:return
        opts=[o for o in choice['options'] if o['id'] != 'decline']
        _answer(eng,opts[0]['id'])
    pytest.fail('choice loop did not finish')


@pytest.mark.parametrize('name',RESIDUE)
def test_every_residue_card_has_complete_bound_abilities(name):
    card=_real(name)
    specs=specs_for(card)
    assert specs
    obj=GameObject(card,owner_id='p1',zone=Zone.HAND)
    bind_from_catalogue(obj)
    assert all(s.ability_kind != '???' for s in specs)


@pytest.mark.parametrize('name,life,hand,creatures,lands',[
    ('Pox',[13,14,12],[3,2,4],[2,2,1],[2,2,4]),
    ('Pox Plague',[10,11,10],[3,2,3],[1,0,0],[2,3,4]),
    ('Fraying Omnipotence',[10,10,9],[2,1,3],[2,1,1],[3,4,6]),
    ('Death Cloud',[18,19,17],[3,1,4],[2,1,0],[1,2,4]),
])
def test_coordinated_edicts_keep_per_player_counts_and_instruction_order(name,life,hand,creatures,lands):
    eng=_three()
    ps=list(eng.state.players)
    for i,p in enumerate(ps):
        p.life=[20,21,19][i];_hand(eng,p.id,[5,3,6][i])
        for j in range([4,3,2][i]):_creature(eng,f'C{i}{j}',p.id)
        for j in range([3,4,6][i]):_land(eng,f'B{i}{j}',p.id)
    _spell(eng,name,x=2);_finish(eng)
    assert [p.life for p in ps] == life
    assert [len(p.hand) for p in ps] == hand
    if name != "Pox Plague":
        assert [sum(o.is_creature for o in eng.state.permanents_controlled_by(p.id)) for p in ps] == creatures
    if name != 'Pox Plague':
        assert [sum(o.is_land for o in eng.state.permanents_controlled_by(p.id)) for p in ps] == lands
    else:
        assert [len(eng.state.permanents_controlled_by(p.id)) for p in ps] == [4,4,4]


@pytest.mark.parametrize('n',[0,2,13])
def test_invitation_chosen_number_survives_pauses_and_clone(n):
    eng=_three();board=[_creature(eng,f'C{i}', 'p2') for i in range(4)]
    _spell(eng,'By Invitation Only')
    assert eng.state.pending_choice['kind']=='choose_number_resolve'
    _answer(eng,n);_finish(eng)
    assert sum(o.zone == Zone.GRAVEYARD for o in board)==min(n,4)


@pytest.mark.parametrize('n,accept,life,remaining',[(0,True,20,4),(0,False,20,0),(2,True,18,4),(2,False,20,2),(100000,False,20,4)])
def test_choice_of_damnations_payer_and_consequence(n,accept,life,remaining):
    eng=_three();p=eng.state.player_by_id('p2')
    board=[_creature(eng,f'C{i}','p2') for i in range(4)]
    _spell(eng,'Choice of Damnations',[p])
    assert eng.state.pending_choice['player_id']=='p2'
    _answer(eng,n)
    choice=eng.state.pending_choice
    assert choice['player_id']=='p1'
    _answer(eng,'yes' if accept else 'decline');_finish(eng)
    assert p.life==life
    assert sum(o.zone == Zone.BATTLEFIELD for o in board)==remaining


def test_invoke_despair_targets_one_opponent_and_repeats_after_discard_or_draw_choices():
    eng=_three();p=eng.state.player_by_id('p2');_library(eng,'p1')
    victims=[_creature(eng,'C1','p2'),_creature(eng,'C2','p2')]
    other=_creature(eng,'Other','p3')
    obj=_spell(eng,'Invoke Despair',[p]);_finish(eng)
    assert sum(len(e.target_specs) for e in obj.spell_effects)==1
    assert p.life==16 and len(eng.state.player_by_id('p1').hand)==2
    assert sum(o.zone == Zone.GRAVEYARD for o in victims)==1 and other.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('pay',[True,False])
def test_rakdos_optional_cost_requires_two_filtered_permanents(pay):
    eng=_three();source=_put(eng,_real('Rakdos, Patron of Chaos'),'p1');_library(eng,'p1')
    p=eng.state.player_by_id('p2');cards=[_creature(eng,f'C{i}','p2') for i in range(3)]
    _land(eng,'Land','p2');token=_creature(eng,'Token','p2');token.is_token=True
    effects=source.triggered_abilities[0].effects
    for e in effects:e.apply(GameContext(eng.state,eng.rules),[p])
    _answer(eng,'pay' if pay else 'decline');_finish(eng)
    assert sum(o.zone==Zone.GRAVEYARD for o in cards)==(2 if pay else 0)
    assert token.zone==Zone.BATTLEFIELD
    assert len(eng.state.player_by_id('p1').hand)==(0 if pay else 2)


def test_possessed_portal_prevents_every_draw_including_empty_library():
    eng=_three();_put(eng,_real('Possessed Portal'),'p1')
    for p in eng.state.players:
        _library(eng,p.id,2);eng.rules.draw(p,3)
        assert len(p.hand)==0 and len(p.library)==2 and not p.has_lost


@pytest.mark.parametrize('pay',[True,False])
def test_meathook_death_payment_preserves_dead_card_and_finality(pay):
    eng=_three();_put(eng,_real('Meathook Massacre II'),'p1')
    victim=_creature(eng,'Victim','p2')
    eng.rules.put_into_graveyard(victim);eng.resolve_until_stable()
    assert eng.state.pending_choice['player_id']=='p2'
    _answer(eng,'pay' if pay else 'decline')
    assert victim.zone==(Zone.GRAVEYARD if pay else Zone.BATTLEFIELD)
    assert eng.state.player_by_id('p2').life==(17 if pay else 20)
    if not pay:
        assert victim.controller_id=='p1' and victim.counters.get('finality')==1
        eng.rules.put_into_graveyard(victim)
        assert victim.zone==Zone.EXILE


def test_meathook_etb_uses_cast_x_instead_of_trigger_x():
    eng=_three();board=[_creature(eng,f'C{i}','p2') for i in range(3)]
    _spell(eng,'Meathook Massacre II',x=2)
    # Sacrifice choices precede death-payment choices.
    for _ in range(20):
        c=eng.state.pending_choice
        if not c:break
        _answer(eng,'pay' if c['kind']=='pay_cost_then' else c['options'][0]['id'])
    assert sum(o.zone==Zone.GRAVEYARD for o in board)==2


@pytest.mark.parametrize('count',[0,1,2])
def test_denizen_partial_sacrifice_then_opponents_optional_source_bound_control(count):
    eng=_three();denizen=_put(eng,_real('Infernal Denizen'),'p1')
    swamps=[_put(eng,_real('Swamp'),'p1') for _ in range(count)]
    _upkeep(eng,'p1')
    if count<2:
        assert denizen.tapped
        if eng.state.pending_choice['kind']=='choose_player_for_source':_answer(eng,'p2')
        assert eng.state.pending_choice['player_id']=='p2'
        _answer(eng,str(denizen.instance_id))
        assert denizen.controller_id=='p2'
    else:assert not denizen.tapped
    assert all(o.zone==Zone.GRAVEYARD for o in swamps)


@pytest.mark.parametrize('fodder',[False,True])
def test_xathrid_success_uses_last_known_power_and_failure_taps_and_loses_life(fodder):
    eng=_three();demon=_put(eng,_real('Xathrid Demon'),'p1')
    victim=None
    if fodder:
        victim=_put(eng,_card('Fodder',is_creature=True,power=5,toughness=5),'p1')
    _upkeep(eng,'p1');_finish(eng)
    assert eng.state.player_by_id('p1').life==(20 if fodder else 13)
    assert eng.state.player_by_id('p2').life==(15 if fodder else 20)
    assert demon.tapped is (not fodder)


@pytest.mark.parametrize('snow,pay',[(True,True),(False,True),(False,False)])
def test_gorilla_optional_forest_and_snow_reward(snow,pay):
    eng=_three();gorilla=_put(eng,_real('Gargantuan Gorilla'),'p1')
    land=_put(eng,_real('Snow-Covered Forest' if snow else 'Forest'),'p1')
    _upkeep(eng,'p1');_answer(eng,'pay' if pay else 'decline');_finish(eng)
    eng.recompute_continuous_effects()
    assert land.zone==(Zone.GRAVEYARD if pay else Zone.BATTLEFIELD)
    assert gorilla.zone==(Zone.BATTLEFIELD if pay else Zone.GRAVEYARD)
    assert eng.state.player_by_id('p1').life==(20 if pay else 13)
    if pay:assert ('trample' in gorilla.granted_keywords or 'trample' in gorilla.temp_keywords)==snow


def test_sugarmaw_only_accepts_artifact_enchantment_or_any_token():
    eng=_three();maw=_put(eng,_real('Devouring Sugarmaw'),'p1')
    _creature(eng,'Plain','p1');_land(eng,'Land','p1')
    _upkeep(eng,'p1')
    assert maw.tapped and eng.state.pending_choice is None
    maw.tapped=False;token=_creature(eng,'Token','p1');token.is_token=True
    _upkeep(eng,'p1');_answer(eng,'pay');_finish(eng)
    assert not maw.tapped and token.zone != Zone.BATTLEFIELD


def test_curse_triggers_on_opponents_upkeep_only_while_suspended():
    eng=_three();p=eng.state.player_by_id('p1')
    curse=GameObject(_real('Curse of the Cabal'),owner_id='p1',zone=Zone.EXILE)
    bind_from_catalogue(curse);curse.counters['time']=2;p.exile.append(curse)
    fodder=_creature(eng,'Fodder','p2')
    _upkeep(eng,'p2')
    assert eng.state.pending_choice['player_id']=='p2'
    _answer(eng,'pay');_finish(eng)
    assert fodder.zone==Zone.GRAVEYARD and curse.counters['time']==4


def test_lich_entry_draw_replacement_damage_and_departure_loss():
    eng=_three();_library(eng,'p1',10)
    lich=_spell(eng,'Lich')
    p=eng.state.player_by_id('p1')
    assert p.life==0 and not p.has_lost
    eng.rules.gain_life(p,3)
    assert p.life==0 and len(p.hand)==3
    fodder=_creature(eng,'Fodder','p1')
    eng.rules.deal_damage(p,1);eng.resolve_until_stable()
    if eng.state.pending_choice:_answer(eng,str(fodder.instance_id))
    assert fodder.zone==Zone.GRAVEYARD and not p.has_lost
    eng.rules.put_into_graveyard(lich);eng.resolve_until_stable()
    assert p.has_lost


def _ready_cast(eng, name, x=0):
    eng.begin_turn();eng.state.current_step='main1'
    p=eng.state.active_player
    obj=GameObject(_real(name),owner_id=p.id,zone=Zone.HAND)
    bind_from_catalogue(obj);p.hand.append(obj)
    p.mana_pool.add_many({c:30 for c in ('W','U','B','R','G','C')})
    return p,obj


def test_devastating_dreams_random_x_cost_excludes_spell_and_runs_before_resolution(monkeypatch):
    eng=_three();p,spell=_ready_cast(eng,'Devastating Dreams')
    _hand(eng,p.id,4);pool=[c for c in p.hand if c is not spell]
    monkeypatch.setattr('random.sample',lambda population,k:list(population)[-k:])
    eng.cast_spell(p,spell,x=2,discard_choices=[c.instance_id for c in pool[:2]])
    assert all(c.zone==Zone.GRAVEYARD for c in pool[-2:])
    assert all(c.zone==Zone.HAND for c in pool[:2])
    assert spell.zone==Zone.STACK
    # Paying is atomic: insufficient cards must reject before mana or hand changes.
    eng2=_three();p2,spell2=_ready_cast(eng2,'Devastating Dreams')
    _hand(eng2,p2.id,1);before=p2.mana_pool.to_dict()
    assert not eng2.can_cast(p2,spell2,x=2)
    assert p2.mana_pool.to_dict()==before and spell2 in p2.hand


@pytest.mark.parametrize('lands',[0,3,4])
def test_tectonic_split_cost_is_half_rounded_up_and_legal_actions_offer_actual_count(lands):
    eng=_three();p,spell=_ready_cast(eng,'Tectonic Split')
    board=[_land(eng,f'Land{i}',p.id) for i in range(lands)]
    actions=[a for a in eng.legal_actions(p) if a.get('type')=='cast_spell' and a.get('instance_id')==spell.instance_id]
    assert actions and actions[0]['sacrifice_count_cost']['count']==(lands+1)//2
    picks=[o.instance_id for o in board[:(lands+1)//2]]
    eng.cast_spell(p,spell,sacrifice_choices=picks)
    assert sum(o.zone==Zone.GRAVEYARD for o in board)==(lands+1)//2
    assert spell.zone==Zone.STACK


@pytest.mark.parametrize('blessing,expected',[(False,1),(True,3)])
def test_vonas_hunger_uses_instead_and_rounds_up(blessing,expected):
    eng=_three();eng.state.player_by_id('p1').has_city_blessing=blessing
    board=[_creature(eng,f'C{i}','p2') for i in range(5)]
    _spell(eng,"Vona's Hunger");_finish(eng)
    assert sum(o.zone==Zone.GRAVEYARD for o in board)==expected


def test_braids_third_chapter_decline_loses_life_to_opponent_and_draws_for_controller():
    eng=_three();braids=_put(eng,_real("Braids's Frightful Return"),'p1');_library(eng,'p1')
    p=eng.state.player_by_id('p2');_creature(eng,'Fodder','p2')
    # Bind the chapter's own ability; chapter selection is independently tested by the Saga suite.
    from mtg_analyzer.game.binding.core import build_effects
    chapter=next(s for s in specs_for(braids.card) if (s.trigger or {}).get('chapter')==[3])
    for e in build_effects(chapter.effects,braids):e.apply(GameContext(eng.state,eng.rules),[p])
    _answer(eng,'decline');_finish(eng)
    assert p.life==18 and len(eng.state.player_by_id('p1').hand)==1


def test_number_choice_and_mass_sacrifice_restore_from_cloned_state():
    from mtg_analyzer.game.game_engine import GameEngine
    eng=_three();board=[_creature(eng,f'C{i}','p2') for i in range(4)]
    _spell(eng,'By Invitation Only');eng=GameEngine(eng.state.clone())
    _answer(eng,2)
    eng=GameEngine(eng.state.clone());_finish(eng)
    assert sum(o.name.startswith('C') for o in eng.state.player_by_id('p2').graveyard)==2


def test_meathook_cannot_return_a_card_that_left_and_reentered_its_graveyard():
    eng=_three();_put(eng,_real('Meathook Massacre II'),'p1');victim=_creature(eng,'Victim','p2')
    eng.rules.put_into_graveyard(victim);eng.resolve_until_stable()
    eng.rules.exile(victim);eng.rules.put_into_graveyard(victim)
    _answer(eng,'decline')
    assert victim.zone==Zone.GRAVEYARD


def test_fraction_counts_prohibited_permanents_but_sacrifices_only_eligible_ones():
    eng=_three();board=[_creature(eng,f'C{i}','p2') for i in range(5)]
    board[0].cant_be_sacrificed_this_turn=True
    from test_par320_edict_counts_punishers import _resolve_spell
    _resolve_spell(eng,'Each player sacrifices half the creatures they control of their choice, rounded up.')
    _finish(eng)
    assert sum(o.zone==Zone.GRAVEYARD for o in board)==3 and board[0].zone==Zone.BATTLEFIELD


def test_denizen_control_ends_when_source_leaves_and_chooser_can_decline():
    eng=_three();denizen=_put(eng,_real('Infernal Denizen'),'p1')
    victim=_creature(eng,'Victim','p1');_upkeep(eng,'p1')
    _answer(eng,'p2');_answer(eng,str(victim.instance_id))
    assert victim.controller_id=='p2'
    eng.rules.put_into_graveyard(denizen);eng.resolve_until_stable()
    assert victim.controller_id=='p1'


def test_curse_intervening_condition_is_rechecked_at_resolution():
    from mtg_analyzer.game.effects.core import GameContext
    eng=_three();p=eng.state.player_by_id('p1')
    curse=GameObject(_real('Curse of the Cabal'),owner_id='p1',zone=Zone.EXILE)
    bind_from_catalogue(curse);p.exile.append(curse)
    fodder=_creature(eng,'Fodder','p2')
    effect=next(a for a in curse.triggered_abilities if a.functions_while_suspended).effects[0]
    effect.apply(GameContext(eng.state,eng.rules))
    assert eng.state.pending_choice is None and fodder.zone==Zone.BATTLEFIELD


def test_lich_insufficient_sacrifices_performs_partial_instruction_then_loses():
    eng=_three();lich=_spell(eng,'Lich');p=eng.state.player_by_id('p1')
    eng.rules.deal_damage(p,2);eng.resolve_until_stable()
    assert lich.zone!=Zone.BATTLEFIELD and p.has_lost


@pytest.mark.parametrize('pay',[True,False])
def test_meathook_own_death_is_controller_payment_not_opponents(pay):
    eng=_three();_put(eng,_real('Meathook Massacre II'),'p1');victim=_creature(eng,'Victim','p1')
    eng.rules.put_into_graveyard(victim);eng.resolve_until_stable()
    assert eng.state.pending_choice['player_id']=='p1'
    _answer(eng,'pay' if pay else 'decline')
    assert victim.zone==(Zone.BATTLEFIELD if pay else Zone.GRAVEYARD)
    assert eng.state.player_by_id('p1').life==(17 if pay else 20)


def test_rakdos_cannot_pay_partial_cost_and_rider_still_draws():
    eng=_three();source=_put(eng,_real('Rakdos, Patron of Chaos'),'p1');_library(eng,'p1')
    victim=_creature(eng,'OnlyOne','p2');p=eng.state.player_by_id('p2')
    source.triggered_abilities[0].effects[0].apply(GameContext(eng.state,eng.rules),[p])
    assert eng.state.pending_choice is None
    assert victim.zone==Zone.BATTLEFIELD and len(eng.state.player_by_id('p1').hand)==2


@pytest.mark.parametrize('text',[
    "Target opponent may sacrifice a creature of their choice. If you don't, you draw a card.",
    "You may sacrifice a creature. If they don't, you draw a card.",
    "As an additional cost to cast this spell, discard X cards at random unless you pay {1}.",
])
def test_new_grammar_rejects_mismatched_players_and_modified_costs(text):
    assert not parse_oracle(_card('Negative',type_line='Sorcery',is_sorcery=True,oracle=text)).modeled


def test_meathook_etb_keeps_announced_x_after_source_returns_to_hand():
    eng=_three();p,hook=_ready_cast(eng,'Meathook Massacre II')
    victim_pid=next(pl.id for pl in eng.state.players if pl.id!=p.id)
    board=[_creature(eng,f'C{i}',victim_pid) for i in range(3)]
    eng.cast_spell(p,hook,x=2)
    eng.rules.resolve_top_of_stack();eng.rules.put_triggers_on_stack()
    assert hook.zone==Zone.BATTLEFIELD and eng.state.stack
    eng.rules.return_to_hand(hook)
    eng.resolve_until_stable();_finish(eng)
    assert sum(o.zone==Zone.GRAVEYARD for o in board)==2
