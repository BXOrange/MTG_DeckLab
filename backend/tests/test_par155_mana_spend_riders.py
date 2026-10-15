"""RULE 106.6 provenance and gameplay for mana counter riders."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.mana_spend_riders import build_rider, arm_next_cast_rider
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_pool import ManaPool, KEEP_UNTIL_END_OF_TURN
from mtg_analyzer.models.mana.mana_cost import ManaCost


def engine():
    eng = GameEngine.new_game([('p1','P1',[]),('p2','P2',[])], starting_hand=0)
    eng.state.current_step = 'main1'
    return eng


def put(eng, name, text='', type_line='Land', zone=Zone.BATTLEFIELD, cost=''):
    card = Card(id=name, name=name, oracle_text=text, type_line=type_line,
                is_land='Land' in type_line, is_creature='Creature' in type_line,
                is_legendary='Legendary' in type_line,
                power=2 if 'Creature' in type_line else None,
                toughness=2 if 'Creature' in type_line else None,
                mana_cost_string=cost)
    obj = GameObject(card, owner_id='p1', zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    elif zone == Zone.HAND:
        eng.state.active_player.hand.append(obj)
    return obj


def tagged(eng, source, rider, count=1, color='G'):
    eng.state.active_player.mana_pool.add(color, count, source_kind='land', rider=build_rider(rider,source))


def cast(eng, subtype='Bear', cost='{G}', legendary=False):
    spell=put(eng,'Test spell',type_line=('Legendary ' if legendary else '')+'Creature — '+subtype,
              zone=Zone.HAND,cost=cost)
    eng.cast_spell(eng.state.active_player,spell)
    eng.rules.check_state_based_actions()
    eng.rules.put_triggers_on_stack()
    return spell


@pytest.mark.parametrize('rider,subtype,bonus',[
    ({'kind':'entry_counters','count':1,'creature':True},'Bear',1),
    ({'kind':'entry_counters','count':1,'creature':True,'exclude_subtype':'Human'},'Human',0),
    ({'kind':'entry_counters','count':1,'creature':True,'exclude_subtype':'Human'},'Bear',1),
    ({'kind':'entry_counters','count':1,'creature':True,'multicolored':True},'Bear',0),
])
def test_payment_rider_filters_and_entry(rider,subtype,bonus):
    eng=engine(); source=put(eng,'Source'); tagged(eng,source,rider)
    spell=cast(eng,subtype)
    assert not spell.counters
    eng.resolve_until_stable()
    assert spell.counters.get('+1/+1',0)==bonus


def test_individual_units_partial_spend_and_activation_payment():
    eng=engine(); source=put(eng,'Source')
    rider={'kind':'entry_counters','count':1,'creature':True}
    tagged(eng,source,rider,3)
    # Paying an activation consumes its own unit without arming any spell.
    pool=eng.state.active_player.mana_pool
    pool.pay(ManaCost.parse('{G}'))
    spell=cast(eng,cost='{G}{G}'); eng.resolve_until_stable()
    assert spell.counters['+1/+1']==2
    pool.add('G')
    second=cast(eng);eng.resolve_until_stable()
    assert not second.counters


def test_next_cast_trigger_independent_of_spent_mana_and_source():
    eng=engine(); source=put(eng,'Camp')
    arm_next_cast_rider(eng.state,source,{'kind':'entry_counters','count':2,'creature':True,'subtype':'Bird','triggered':True})
    eng.rules._move_to_graveyard(source)
    eng.state.active_player.mana_pool.add('G',3)
    bear=cast(eng);eng.resolve_until_stable();assert not bear.counters
    bird=cast(eng,'Bird')
    assert len(eng.state.stack)==2
    eng.resolve_until_stable();assert bird.counters['+1/+1']==2
    nextbird=cast(eng,'Bird');eng.resolve_until_stable();assert not nextbird.counters


def test_next_cast_expiry():
    eng=engine(); source=put(eng,'Yuna')
    arm_next_cast_rider(eng.state,source,{'kind':'entry_counters','count':2,'creature':True,'triggered':True})
    eng.state.internal_turn.number+=1
    eng.state.active_player.mana_pool.add('G')
    spell=cast(eng);eng.resolve_until_stable();assert not spell.counters


def test_delayed_source_counter_waits_for_trigger_and_old_incarnation():
    eng=engine();source=put(eng,'City')
    tagged(eng,source,{'kind':'source_counters','count':1,'legendary':True,'triggered':True})
    spell=cast(eng,legendary=True)
    assert len(eng.state.stack)==2 and not source.counters
    eng.rules._move_to_graveyard(source)
    eng.state.active_player.graveyard.remove(source)
    eng.state.add_to_battlefield(source)
    eng.resolve_until_stable();assert not source.counters


def test_delayed_jade_counter_and_hexproof():
    eng=engine();source=put(eng,'Orb')
    tagged(eng,source,{'kind':'entry_counters','count':1,'creature':True,'subtype':'Dragon',
                      'triggered':True,'keyword':'hexproof'})
    spell=cast(eng,'Dragon')
    assert len(eng.state.stack)==2 and not spell.counters
    eng.resolve_until_stable();eng.recompute_continuous_effects()
    assert spell.counters['+1/+1']==1
    assert 'hexproof' in spell.granted_keywords


def test_kept_mana_retains_rider_and_editor_removal_clears_it():
    pool=ManaPool();rider={'kind':'entry_counters','count':1}
    pool.add('G',1,rider=rider,keep_until=KEEP_UNTIL_END_OF_TURN)
    pool.empty();pool.pay(ManaCost.parse('{G}'))
    assert pool.last_payment_riders==[rider]
    pool.add('G',rider=rider);pool.set_amount('G',0);pool.add('G')
    pool.pay(ManaCost.parse('{G}'));assert not pool.last_payment_riders

@pytest.mark.parametrize('name,text,subtype,count',[
    ('Animal Attendant','{T}: Add one mana of any color. If that mana is spent to cast a non-Human creature spell, that creature enters with an additional +1/+1 counter on it.','Bear',1),
    ('Biophagus','Genomic Enhancement — {T}: Add one mana of any color. If this mana is spent to cast a creature spell, that creature enters with an additional +1/+1 counter on it.','Bear',1),
    ('Jade Orb of Dragonkind',"{T}: Add {G}. When you spend this mana to cast a Dragon creature spell, it enters with an additional +1/+1 counter on it and gains hexproof until your next turn. (It can't be the target of spells or abilities your opponents control.)",'Dragon',1),
    ('Chocobo Camp','{T}: Add {G}. When you next cast a Bird creature spell this turn, it enters with an additional +1/+1 counter on it.','Bird',1),
    ('Yuna, Grand Summoner','Grand Summon — {T}: Add one mana of any color. When you next cast a creature spell this turn, that creature enters with two additional +1/+1 counters on it.','Bear',2),
])
def test_real_raw_mana_to_spell_entry(name,text,subtype,count):
    eng=engine();source=put(eng,name,text)
    produced=eng.tap_for_mana(eng.state.active_player,source)
    color=next(iter(produced))
    spell=cast(eng,subtype,cost='{'+color+'}')
    if name in {'Jade Orb of Dragonkind','Chocobo Camp','Yuna, Grand Summoner'}:
        assert len(eng.state.stack)==2
    eng.resolve_until_stable()
    assert spell.counters.get('+1/+1')==count


def test_real_guildmages_forum_and_goblin_experience():
    eng=engine();pool=eng.state.active_player.mana_pool
    source=put(eng,"Guildmages' Forum",'{T}: Add {C}.\n{1}, {T}: Add one mana of any color. If that mana is spent on a multicolored creature spell, that creature enters with an additional +1/+1 counter on it.')
    pool.add('C');eng.tap_for_mana(eng.state.active_player,source,ability_index=1)
    pool.add('G')
    spell=put(eng,'Gold Bear',type_line='Creature — Bear',zone=Zone.HAND,cost='{W}{G}')
    spell.card.color_identity={'W','G'}
    eng.cast_spell(eng.state.active_player,spell);eng.resolve_until_stable()
    assert spell.counters['+1/+1']==1
    goblin=put(eng,'The Goblin Sparring Grounds','{T}: Add {R}. If this mana is spent to cast a Goblin spell, you get an experience counter.')
    eng.tap_for_mana(eng.state.active_player,goblin)
    spell=cast(eng,'Goblin',cost='{R}');eng.resolve_until_stable()
    assert eng.state.active_player.counters.get('experience')==1
    assert not spell.counters


def test_real_opal_palace_uses_command_cast_count():
    eng=engine();player=eng.state.active_player
    commander=put(eng,'Commander',type_line='Legendary Creature — Bear',zone=Zone.HAND,cost='{G}')
    player.hand.remove(commander);commander.zone=Zone.COMMAND;commander.is_commander=True
    commander.card.color_identity={'G'}
    player.command.append(commander);player.commander_casts[commander.instance_id]=2
    source=put(eng,'Opal Palace',"{T}: Add {C}.\n{1}, {T}: Add one mana of any color in your commander's color identity. If you spend this mana to cast your commander, it enters with a number of additional +1/+1 counters on it equal to the number of times it's been cast from the command zone this game.")
    player.mana_pool.add('C',5)
    eng.tap_for_mana(player,source,ability_index=1)
    eng.cast_spell(player,commander);eng.resolve_until_stable()
    assert commander.counters['+1/+1']==3


def test_real_magical_city_legendary_trigger():
    eng=engine();source=put(eng,'The Magical City, New','{T}: Add {W}, {U}, or {R}. When this mana is spent to cast a legendary spell, put a +1/+1 counter on this land.')
    eng.tap_for_mana(eng.state.active_player,source)
    assert not source.counters
    spell=cast(eng,cost='{W}',legendary=True)
    assert not source.counters and len(eng.state.stack)==2
    eng.resolve_until_stable();assert source.counters['+1/+1']==1


def test_real_solar_array_sunburst_is_delayed():
    eng=engine();source=put(eng,'Solar Array','{T}: Add {C}. When you next cast an artifact spell this turn, that spell gains sunburst.')
    eng.tap_for_mana(eng.state.active_player,source)
    spell=put(eng,'Artifact',type_line='Artifact',zone=Zone.HAND,cost='{1}')
    eng.cast_spell(eng.state.active_player,spell);eng.rules.put_triggers_on_stack()
    assert len(eng.state.stack)==2
    eng.resolve_until_stable()
    assert not spell.counters  # colorless produces no sunburst counter


def test_countered_entry_marks_do_not_follow_reanimation_or_spell_copy():
    eng=engine();source=put(eng,'Biophagus')
    tagged(eng,source,{'kind':'entry_counters','count':1,'creature':True})
    spell=cast(eng)
    [copy_item]=eng.rules.copy_spell(eng.state.stack[0],'p1')
    eng.resolve_until_stable()
    assert not copy_item.obj.counters
    assert spell.counters['+1/+1']==1
    eng.rules._move_to_graveyard(spell)
    eng.state.active_player.graveyard.remove(spell)
    spell.counters={}
    eng.rules._apply_entry_counters(spell)
    eng.state.add_to_battlefield(spell)
    assert not spell.counters


def test_counter_replacement_scales_spend_entry_payoff():
    eng=engine();put(eng,'Doubling Season',type_line='Enchantment')
    source=put(eng,'Biophagus','{T}: Add one mana of any color. If this mana is spent to cast a creature spell, that creature enters with an additional +1/+1 counter on it.')
    eng.tap_for_mana(eng.state.active_player,source)
    spell=cast(eng,cost='{W}');eng.resolve_until_stable()
    assert spell.counters['+1/+1']==2


def test_real_nyxbloom_each_produced_unit_adds_entry_counter():
    eng=engine();put(eng,'Nyxbloom Ancient',type_line='Enchantment Creature — Elemental')
    source=put(eng,'Biophagus','{T}: Add one mana of any color. If this mana is spent to cast a creature spell, that creature enters with an additional +1/+1 counter on it.')
    produced=eng.tap_for_mana(eng.state.active_player,source)
    assert produced=={'W':3}
    spell=cast(eng,cost='{W}{W}{W}');eng.resolve_until_stable()
    assert spell.counters['+1/+1']==3


def test_hardened_scales_applies_once_to_combined_entry_counters():
    eng=engine();put(eng,'Hardened Scales','If one or more +1/+1 counters would be put on a creature you control, that many plus one +1/+1 counters are put on it instead.',type_line='Enchantment')
    source=put(eng,'Source');tagged(eng,source,{'kind':'entry_counters','count':1,'creature':True},3)
    spell=cast(eng,cost='{G}{G}{G}');eng.resolve_until_stable()
    assert spell.counters['+1/+1']==4


def test_countered_spell_reanimated_does_not_keep_entry_rider():
    eng=engine();source=put(eng,'Source');tagged(eng,source,{'kind':'entry_counters','count':1,'creature':True})
    spell=cast(eng)
    eng.state.stack.clear();eng.rules._move_to_graveyard(spell)
    eng.state.active_player.graveyard.remove(spell)
    eng.rules._apply_entry_counters(spell);eng.state.add_to_battlefield(spell)
    assert not spell.counters


def test_countered_delayed_trigger_does_not_grant_entry_counters():
    eng=engine();source=put(eng,'Camp')
    arm_next_cast_rider(eng.state,source,{'kind':'entry_counters','count':1,'creature':True})
    eng.state.active_player.mana_pool.add('G')
    spell=cast(eng)
    assert len(eng.state.stack)==2
    eng.state.stack.pop()  # RULE 701.5: counter the independent delayed trigger.
    eng.resolve_until_stable();assert not spell.counters


def test_jade_hexproof_expires_before_spell_enters_on_next_turn():
    from mtg_analyzer.game.durations import sweep
    eng=engine();source=put(eng,'Orb')
    tagged(eng,source,{'kind':'entry_counters','count':1,'creature':True,'subtype':'Dragon',
                      'triggered':True,'keyword':'hexproof'})
    spell=cast(eng,'Dragon')
    eng.rules.resolve_top_of_stack()
    assert eng.state.floating_statics
    eng.state.internal_turn.number+=1
    sweep(eng.state,'turn_begin')
    eng.resolve_until_stable();eng.recompute_continuous_effects()
    assert spell.counters['+1/+1']==1
    assert 'hexproof' not in spell.granted_keywords


def test_shadow_lots_do_not_credit_wrong_source_or_unused_colors():
    pool=ManaPool();rider={'kind':'entry_counters','count':1}
    pool.add('G',1,source_kind='creature',rider=rider)
    pool.add('G',1,source_kind='basic_land')
    pool.pay(ManaCost.parse('{G}'),require_source_kind='basic_land')
    assert not pool.last_payment_riders
    pool.pay(ManaCost.parse('{G}'))
    assert pool.last_payment_riders==[rider]
    pool.add('G',1,rider=rider);pool.add('W',1)
    pool.pay(ManaCost.parse('{W}'));assert not pool.last_payment_riders


def test_native_and_mana_entry_counters_share_one_replacement_placement():
    eng=engine()
    put(eng,'Hardened Scales','If one or more +1/+1 counters would be put on a creature you control, that many plus one +1/+1 counters are put on it instead.',type_line='Enchantment')
    source=put(eng,'Source');tagged(eng,source,{'kind':'entry_counters','count':1,'creature':True})
    spell=put(eng,'Counter Bear','This creature enters with two +1/+1 counters on it.',type_line='Creature — Bear',zone=Zone.HAND,cost='{G}')
    eng.cast_spell(eng.state.active_player,spell);eng.resolve_until_stable()
    assert spell.counters['+1/+1']==4  # native two + mana one + replacement one


def test_mana_spend_experience_is_present_when_cast_trigger_checks_condition():
    from mtg_analyzer.models.game.events import EventType
    eng=engine()
    source=put(eng,'The Goblin Sparring Grounds','{T}: Add {R}. If this mana is spent to cast a Goblin spell, you get an experience counter.')
    eng.tap_for_mana(eng.state.active_player,source)
    observed=[]
    eng.state.subscribe(lambda event: observed.append(eng.state.active_player.counters.get('experience',0))
                        if event.type==EventType.SPELL_CAST else None)
    cast(eng,'Goblin',cost='{R}')
    assert observed==[1]
