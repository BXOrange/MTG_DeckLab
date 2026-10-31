"""Command-zone emblems use live cast, activation, death and combat events."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import build_effects, bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

DACK='whenever you cast a spell that targets 1 or more permanents, gain control of those permanents'
ROWAN="whenever you activate an ability that isn't a mana ability, copy it. you may choose new targets for the copy"
DARETTI='whenever an artifact is put into your graveyard from the battlefield, return that card to the battlefield at the beginning of the next end step'
ZARIEL='at the end of the first combat phase on your turn, untap target creature you control. after this phase, there is an additional combat phase'


def engine():
    eng=GameEngine.new_game([('p1','P1',[]),('p2','P2',[])],starting_hand=0)
    eng.state.current_step='main1'
    return eng


def put(eng,name='Bear',owner='p2',kind='Creature — Bear',text='',zone=Zone.BATTLEFIELD):
    card=Card(id=name,name=name,type_line=kind,oracle_text=text,
              is_creature='Creature' in kind,is_instant=kind=='Instant',
              is_sorcery=kind=='Sorcery',
              power=2 if 'Creature' in kind else None,toughness=2 if 'Creature' in kind else None,
              mana_cost_string='{0}' if kind=='Instant' else '')
    obj=GameObject(card,owner_id=owner,zone=zone);bind_from_catalogue(obj);obj.summoning_sick=False
    if zone==Zone.HAND:
        eng.state.player_by_id(owner).hand.append(obj)
    else:
        eng.state.add_to_battlefield(obj)
    return obj


def emblem(eng,text,owner='p1'):
    source=put(eng,'Planeswalker',owner,'Enchantment')
    specs=match_clause('you get an emblem with "'+text+'."')
    assert specs is not None
    context=GameContext(eng.state,eng.rules)
    for effect in build_effects(specs,source=source):
        effect.apply(context)
    eng.rules.destroy(source);eng.resolve_until_stable()
    assert eng.state.player_by_id(owner).emblems
    return source


def cast_target(eng,target):
    spell=put(eng,'Tap spell','p1','Instant','Tap target creature.',zone=Zone.HAND)
    eng.cast_spell(eng.state.players[0],spell,targets=[target])
    eng.rules.put_triggers_on_stack()
    return spell


def test_dack_emblem_works_after_planeswalker_leaves_and_is_not_targeted():
    eng=engine();emblem(eng,DACK);target=put(eng)
    target.intrinsic_keywords.add('hexproof')
    # The spell must legally target it; hexproof starts only after casting.
    target.intrinsic_keywords.clear();cast_target(eng,target)
    target.intrinsic_keywords.add('hexproof')
    eng.rules.resolve_top_of_stack()
    assert target.controller_id=='p1' and not target.tapped
    eng.resolve_until_stable();assert target.tapped


def test_dack_uses_original_targets_when_spell_retargeted():
    eng=engine();emblem(eng,DACK);original=put(eng,'Original');later=put(eng,'Later')
    cast_target(eng,original)
    spell_item=next(i for i in eng.state.stack if i.kind=='spell')
    spell_item.targets=[later]
    eng.rules.resolve_top_of_stack()
    assert original.controller_id=='p1' and later.controller_id=='p2'


def test_dack_does_not_take_new_incarnation_or_newly_chosen_target():
    eng=engine();emblem(eng,DACK);target=put(eng)
    cast_target(eng,target)
    eng.rules._move_to_graveyard(target)
    eng.rules.return_from_graveyard(target)
    eng.rules.resolve_top_of_stack()
    assert target.controller_id=='p2'


def test_rowan_copies_ordinary_ability_once_but_not_mana():
    eng=engine();emblem(eng,ROWAN)
    source=put(eng,'Device','p1','Artifact','{0}: You gain 2 life.\n{T}: Add {G}.')
    before=eng.state.players[0].life
    eng.activate_ability(eng.state.players[0],source)
    eng.resolve_until_stable()
    assert eng.state.players[0].life==before+4
    eng.tap_for_mana(eng.state.players[0],source)
    assert eng.state.players[0].mana_pool.pool['G']==1 and not eng.rules.pending_triggers


def test_rowan_does_not_copy_opponents_ability():
    eng=engine();emblem(eng,ROWAN)
    source=put(eng,'Enemy device','p2','Artifact','{0}: You gain 2 life.')
    before=eng.state.players[1].life
    eng.activate_ability(eng.state.players[1],source)
    eng.resolve_until_stable();assert eng.state.players[1].life==before+2


def test_daretti_returns_owned_artifact_even_if_opponent_controlled_it():
    eng=engine();emblem(eng,DARETTI)
    artifact=put(eng,'Artifact','p1','Artifact');artifact.controller_id='p2'
    eng.rules.destroy(artifact);eng.resolve_until_stable()
    assert artifact.zone==Zone.GRAVEYARD and eng.state.delayed_triggers
    eng._fire_delayed_triggers('end');eng.resolve_until_stable()
    assert artifact.zone==Zone.BATTLEFIELD and artifact.controller_id=='p1'


def test_daretti_ignores_opponents_owned_artifact_and_graveyard_revisit():
    eng=engine();emblem(eng,DARETTI)
    enemy=put(eng,'Enemy','p2','Artifact');eng.rules.destroy(enemy);eng.resolve_until_stable()
    assert not eng.state.delayed_triggers
    artifact=put(eng,'Mine','p1','Artifact');eng.rules.destroy(artifact);eng.resolve_until_stable()
    eng.state.players[0].graveyard.remove(artifact);artifact.zone=Zone.EXILE;eng.state.players[0].exile.append(artifact)
    eng.state.players[0].exile.remove(artifact);artifact.zone=Zone.GRAVEYARD;eng.state.players[0].graveyard.append(artifact)
    eng._fire_delayed_triggers('end');eng.resolve_until_stable()
    assert artifact.zone==Zone.GRAVEYARD


def test_zariel_only_first_own_combat_and_targeted_untap():
    eng=engine();emblem(eng,ZARIEL)
    creature=put(eng,'Own','p1');creature.tapped=True
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='begin_combat',phase='combat'))
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='end_combat',phase='combat'))
    eng.rules.put_triggers_on_stack()
    assert eng.state.stack or eng.state.pending_choice
    if eng.state.pending_choice:
        option=next(o['id'] for o in eng.state.pending_choice['options'] if o.get('instance_id')==creature.instance_id)
        eng.resolve_pending_choice(option)
    eng.resolve_until_stable()
    assert not creature.tapped and len(eng.state.pending_extra_combats)==1
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='begin_combat',phase='combat'))
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='end_combat',phase='combat'))
    assert not eng.rules.pending_triggers


def test_rowan_offers_new_targets_for_copy_before_it_resolves():
    eng=engine();emblem(eng,ROWAN)
    source=put(eng,'Healer','p1','Artifact','{0}: Target player gains 2 life.')
    first,second=eng.state.players
    eng.activate_ability(first,source,targets=[first]);eng.resolve_until_stable()
    choice=eng.state.pending_choice
    assert choice and choice['kind']=='copy_targets'
    answer=next(o['id'] for o in choice['options'] if o.get('player_id')=='p2')
    eng.resolve_pending_choice(answer);eng.resolve_until_stable()
    assert first.life==42 and second.life==42


def test_dack_captured_targets_survive_cast_spell_being_countered():
    eng=engine();emblem(eng,DACK);target=put(eng)
    cast_target(eng,target)
    item=next(i for i in eng.state.stack if i.kind=='spell')
    eng.state.stack.remove(item);eng.rules._move_to_graveyard(item.obj)
    eng.resolve_until_stable();assert target.controller_id=='p1'


def test_daretti_multiple_deaths_have_independent_delayed_returns():
    eng=engine();emblem(eng,DARETTI)
    artifacts=[put(eng,f'Artifact{i}','p1','Artifact') for i in range(2)]
    for artifact in artifacts:eng.rules.destroy(artifact)
    eng.resolve_until_stable();assert len(eng.state.delayed_triggers)==2
    eng._fire_delayed_triggers('end');eng.resolve_until_stable()
    assert all(a.zone==Zone.BATTLEFIELD for a in artifacts)


def test_zariel_does_not_trigger_during_opponents_first_combat():
    eng=engine();emblem(eng,ZARIEL);put(eng,'Own','p1')
    eng.state.active_player_index=1
    for step in ('begin_combat','end_combat'):
        eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step=step,phase='combat'))
    assert not eng.rules.pending_triggers


def test_emblem_unknown_tail_and_first_combat_variant_fail_closed():
    assert match_clause('you get an emblem with "'+DACK+', then draw a card."') is None
    assert match_clause('you get an emblem with "'+ZARIEL.replace('first combat','third combat')+'."') is None


SORIN="at the beginning of each opponent's upkeep, that player sacrifices a creature of their choice"
SEEK="at the beginning of your upkeep, pay {u}{b}{r}. if you don't, you lose the game"


def upkeep(eng, active):
    eng.state.active_player_index=active
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep',phase='beginning'))
    eng.resolve_until_stable()


def test_sorin_emblem_opponent_chooses_and_own_upkeep_does_not_trigger():
    eng=engine();emblem(eng,SORIN)
    own=put(eng,'Own','p1');first=put(eng,'First');second=put(eng,'Second')
    upkeep(eng,0);assert not eng.state.pending_choice
    upkeep(eng,1)
    choice=eng.state.pending_choice
    assert choice and choice['player_id']=='p2'
    eng.resolve_pending_choice(str(second.instance_id));eng.resolve_until_stable()
    assert second.zone==Zone.GRAVEYARD and first.zone==own.zone==Zone.BATTLEFIELD


def test_seek_emblem_unpayable_upkeep_loses_game():
    eng=engine();emblem(eng,SEEK)
    upkeep(eng,1);assert not eng.state.players[0].has_lost
    upkeep(eng,0)
    assert eng.state.players[0].has_lost


def test_emblem_sacrifice_then_draw_acts_for_that_player():
    eng=engine();emblem(eng,SORIN+' and draws a card')
    for pl in eng.state.players:
        pl.library.append(GameObject(Card(id='f'+pl.id,name='F',type_line='Sorcery'),owner_id=pl.id,zone=Zone.LIBRARY))
    victim=put(eng,'Victim');p1,p2=eng.state.players
    upkeep(eng,1)
    while eng.state.pending_choice:
        eng.resolve_pending_choice(str(victim.instance_id));eng.resolve_until_stable()
    assert victim.zone==Zone.GRAVEYARD and len(p2.hand)==1 and not p1.hand


def test_emblem_payment_unknown_tail_fails_closed():
    assert match_clause('you get an emblem with "'+SEEK+' and draw a card."') is None


KAYA=('at the beginning of your upkeep, you may cast a legendary spell from your hand, '
      'from your graveyard, or from among cards you own in exile without paying its mana cost')


@pytest.mark.parametrize('zone',[Zone.HAND,Zone.GRAVEYARD,Zone.EXILE])
def test_kaya_emblem_casts_one_legendary_spell_during_upkeep_from_each_zone(zone):
    eng=engine();emblem(eng,KAYA)
    spell=put(eng,'Legend','p1','Legendary Creature — Wizard',zone=Zone.HAND)
    other=put(eng,'Ordinary','p1','Creature — Wizard',zone=Zone.HAND)
    if zone!=Zone.HAND:
        eng.state.players[0].hand.remove(spell)
        spell.zone=zone;getattr(eng.state.players[0],zone.value).append(spell)
    upkeep(eng,0)
    choice=eng.state.resolution_play_choice
    assert choice and spell.instance_id in choice['instance_ids']
    assert other.instance_id not in choice['instance_ids']
    eng.play_resolution_card(eng.state.players[0],spell)
    assert eng.state.resolution_play_choice is None
    eng.resolve_until_stable()
    assert spell.zone==Zone.BATTLEFIELD
    assert not eng.state.free_cast_instance_ids


def test_seek_emblem_pay_or_decline_choice():
    eng=engine();emblem(eng,SEEK)
    player=eng.state.players[0]
    for color in ('U','B','R'):player.mana_pool.add(color,1)
    upkeep(eng,0)
    assert eng.state.pending_choice
    eng.resolve_pending_choice('pay');eng.resolve_until_stable()
    assert not player.has_lost and all(player.mana_pool.pool.get(c,0)==0 for c in ('U','B','R'))


LOLTH=('whenever an opponent is dealt combat damage by 1 or more creatures you control, '
       'if that player lost less than 8 life this turn, they lose life equal to the difference')


@pytest.mark.parametrize('prior,additional,expected',[(0,0,8),(3,0,8),(0,6,8),(0,9,11),(7,0,9)])
def test_lolth_uses_total_life_lost_and_rechecks_at_resolution(prior,additional,expected):
    eng=engine();emblem(eng,LOLTH)
    attacker=put(eng,'Attacker','p1');opponent=eng.state.players[1]
    initial=opponent.life
    if prior:eng.rules.lose_life(opponent,prior)
    eng.rules.deal_damage(opponent,2,source=attacker,combat=True)
    eng.state.fire_event(GameEvent(EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
        player_id='p1',target_id='p2',is_player=True,contributor_ids=[attacker.instance_id],
        contributor_amounts=[2]))
    eng.rules.put_triggers_on_stack()
    if additional:eng.rules.lose_life(opponent,additional)
    eng.resolve_until_stable()
    assert initial-opponent.life==expected


def test_chandra_emblem_actual_source_deals_mana_spent_damage():
    eng=engine()
    emblem(eng,'whenever you cast a red spell, this emblem deals x damage to any target, where x is the amount of mana spent to cast that spell')
    spell=put(eng,'Red spell','p1','Instant','You gain 1 life.',zone=Zone.HAND)
    spell.card.color_identity={'R'};spell.card.mana_cost_string='{2}{R}'
    eng.state.players[0].mana_pool.add('R',3)
    eng.cast_spell(eng.state.players[0],spell)
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        choice=eng.state.pending_choice
        opt='p2'
        eng.resolve_pending_choice(opt);eng.resolve_until_stable()
    assert eng.state.players[1].life==37


def test_ersta_emblem_twenty_wizard_intervening_threshold():
    eng=engine();emblem(eng,'at the beginning of your upkeep, if you control 20 or more wizards, you win the game')
    wizards=[put(eng,f'Wizard{i}','p1','Creature — Wizard') for i in range(20)]
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep',phase='beginning'))
    eng.rules.put_triggers_on_stack();assert eng.state.stack
    eng.rules.destroy(wizards[0]);eng.resolve_until_stable()
    assert not eng.state.players[1].has_lost
    put(eng,'Replacement wizard','p1','Creature — Wizard')
    upkeep(eng,0)
    assert eng.state.players[1].has_lost


@pytest.mark.parametrize('kind,color,copies',[('Instant','R',2),('Sorcery','R',2),('Instant','U',0)])
def test_jaya_live_emblem_copies_each_red_instant_or_sorcery_twice(kind,color,copies):
    eng=engine();emblem(eng,'whenever you cast a red instant or sorcery spell, copy it twice. you may choose new targets for the copies')
    spell=put(eng,'Spell','p1',kind,'You gain 1 life.',zone=Zone.HAND)
    spell.card.is_sorcery=kind=='Sorcery';spell.card.color_identity={color};spell.card.mana_cost_string='{'+color+'}';eng.state.players[0].mana_pool.add(color,1)
    before=eng.state.players[0].life
    eng.cast_spell(eng.state.players[0],spell);eng.resolve_until_stable()
    while eng.state.pending_choice:
        eng.resolve_pending_choice('keep');eng.resolve_until_stable()
    assert eng.state.players[0].life==before+1+copies


@pytest.mark.parametrize('phrase,kind,color',[
    ('a permanent card','Artifact',None),
    ('a blue or black creature card','Creature — Wizard','U'),
    ('a blue or black creature card','Creature — Wizard','B'),
])
def test_emblem_library_search_filters_and_puts_selected_card_on_battlefield(phrase,kind,color):
    eng=engine();emblem(eng,'at the beginning of your end step, search your library for '+phrase+', put it onto the battlefield, then shuffle')
    player=eng.state.players[0]
    selected=put(eng,'Selected','p1',kind,zone=Zone.HAND)
    excluded=put(eng,'Excluded','p1','Conspiracy',zone=Zone.HAND)
    if color:selected.card.color_identity={color};selected.card.mana_cost_string='{'+color+'}'
    for obj in (selected,excluded):
        player.hand.remove(obj);obj.zone=Zone.LIBRARY;player.library.append(obj)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='end',phase='ending'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice
    options=eng.state.pending_choice['options']
    assert any(str(selected.instance_id)==o['id'] for o in options)
    assert not any(str(excluded.instance_id)==o['id'] for o in options)
    eng.resolve_pending_choice(str(selected.instance_id));eng.resolve_until_stable()
    assert selected.zone==Zone.BATTLEFIELD and excluded.zone==Zone.LIBRARY
    assert any(event.type==EventType.SHUFFLE for event in eng.state.event_log)


def test_tezzeret_emblem_permanently_animates_own_artifact():
    eng=engine();emblem(eng,'at the beginning of combat on your turn, target artifact you control becomes an artifact creature with base power and toughness 5/5')
    own=put(eng,'Own artifact','p1','Artifact');enemy=put(eng,'Enemy artifact','p2','Artifact')
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='begin_combat',phase='combat'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice
    eng.resolve_pending_choice(str(own.instance_id));eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert own.is_creature and (own.power,own.toughness)==(5,5)
    assert not enemy.is_creature
    eng.state.internal_turn.number+=1;eng.recompute_continuous_effects()
    assert own.is_creature and (own.power,own.toughness)==(5,5)


@pytest.mark.parametrize('host_controller',['p1','p2'])
def test_nested_emblem_quote_granted_to_enchanted_planeswalker_executes(host_controller):
    eng=engine()
    pw=put(eng,'Walker',host_controller,'Planeswalker')
    pw.card.loyalty=12
    pw.add_counters('loyalty',12)
    text=('Enchanted planeswalker has "[−12]: You get an emblem with '
          "'You may activate loyalty abilities of planeswalkers you control on any player's turn "
          "any time you could cast an instant.'\"")
    aura=put(eng,'Talent','p1','Enchantment — Aura',text)
    aura.attached_to=pw.instance_id
    eng.recompute_continuous_effects()
    assert pw.granted_activated_abilities
    assert pw.granted_activated_abilities[0].cost.loyalty==-12
    eng.state.active_player_index=0 if host_controller=='p1' else 1
    controller=eng.state.player_by_id(host_controller)
    eng.activate_ability(controller,pw);eng.resolve_until_stable()
    assert controller.emblems
    assert pw.zone==Zone.GRAVEYARD
