"""Real counter/pump then fight announcements and resolution."""
import pytest
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from test_mec106_gift import _engine, _bf, _creature, _hand, _spell, _cast

ORACLE = {'Blizzard Brawl': "Choose target creature you control and target creature you don't control. If you control three or more snow permanents, the creature you control gets +1/+0 and gains indestructible until end of turn. Then those creatures fight each other. (Each deals damage equal to its power to the other.)", 'Duel for Dominance': "Coven — Choose target creature you control and target creature you don't control. If you control three or more creatures with different powers, put a +1/+1 counter on the chosen creature you control. Then the chosen creatures fight each other. (Each deals damage equal to its power to the other.)", 'Hog-Monkey Rampage': 'Choose target creature you control and target creature an opponent controls. Put a +1/+1 counter on the creature you control if it has power 4 or greater. Then those creatures fight each other. (Each deals damage equal to its power to the other.)', 'Joust': "Choose target creature you control and target creature you don't control. The creature you control gets +2/+1 until end of turn if it's a Knight. Then those creatures fight each other. (Each deals damage equal to its power to the other.)", 'Malamet Battle Glyph': "Choose target creature you control and target creature you don't control. If the creature you control entered this turn, put a +1/+1 counter on it. Then those creatures fight each other.", 'Tail Swipe': "Choose target creature you control and target creature you don't control. If you cast this spell during your main phase, the creature you control gets +1/+1 until end of turn. Then those creatures fight each other. (Each deals damage equal to its power to the other.)", 'Savage Punch': "Target creature you control fights target creature you don't control.\nFerocious — The creature you control gets +2/+2 until end of turn before it fights if you control a creature with power 4 or greater.", 'Algorithmic Ferocity': 'Until end of turn, target creature you control gains indestructible and gets +1/+0 for each card in your hand with mana value 4 or greater. Then it fights target creature an opponent controls.', 'Ancient Animus': "Put a +1/+1 counter on target creature you control if it's legendary. Then it fights target creature an opponent controls. (Each deals damage equal to its power to the other.)", "Ent's Fury": "Put a +1/+1 counter on target creature you control if its power is 4 or greater. Then that creature gets +1/+1 until end of turn and fights target creature you don't control.", 'Hunt the Hunter': 'Target green creature you control gets +2/+2 until end of turn. It fights target green creature an opponent controls.', 'Savage Swipe': "Target creature you control gets +2/+2 until end of turn if its power is 2. Then it fights target creature you don't control. (Each deals damage equal to its power to the other.)", 'Really Epic Punch': "Target creature you control gets +2/+2 if it's a host or has augment. Then it fights target creature you don't control.", 'Fight for the Throne': 'Put a +1/+1 counter on target creature you control. Then it fights target creature an opponent controls. When the creature an opponent controls dies this turn, if you control your commander, you become the monarch.', "Rhino's Rampage": 'Target creature you control gets +1/+0 until end of turn. It fights target creature an opponent controls. When excess damage is dealt to the creature an opponent controls this way, destroy up to one target noncreature artifact with mana value 3 or less.', 'Temur Charm': "Choose one —\n• Target creature you control gets +1/+1 until end of turn. It fights target creature you don't control.\n• Counter target spell unless its controller pays {3}.\n• Creatures with power 3 or less can't block this turn.", 'Kraul Harpooner': "Reach\nUndergrowth — When this creature enters, choose up to one target creature you don't control with flying. This creature gets +X/+0 until end of turn, where X is the number of creature cards in your graveyard, then you may have this creature fight that creature.", 'Ace, Fearless Rebel': "Nitro-9 — Whenever Ace attacks, you may sacrifice an artifact. When you do, put a +1/+1 counter on Ace, then it fights up to one target creature defending player controls.\nDoctor's companion (You can have two commanders if the other is the Doctor.)", 'Gimli, Mournful Avenger': "Gimli has indestructible as long as two or more creatures died under your control this turn.\nWhenever another creature you control dies, put a +1/+1 counter on Gimli. When this ability resolves for the third time this turn, Gimli fights up to one target creature you don't control.", 'Alexander Clamilton': "Whenever you cast a wordy spell, scry 2. (A spell is wordy if it has four or more lines of rules text.)\n{1}{R}, {T}: Choose target creature you don't control. Reveal the top card of your library. Alexander Clamilton gets +X/+0 until end of turn, where X is the number of lines of rules text of the revealed card. Alexander Clamilton fights that creature."}

@pytest.mark.parametrize('name',["Blizzard Brawl","Duel for Dominance","Hog-Monkey Rampage","Joust","Malamet Battle Glyph","Tail Swipe","Ancient Animus","Ent's Fury","Hunt the Hunter","Savage Swipe","Really Epic Punch","Savage Punch"])
def test_real_immediate_fight(name):
    eng=_engine()
    own=_bf(eng,_creature('Friendly',4,20))
    enemy=_bf(eng,_creature('Enemy',2,20),player='p2')
    own.card.color_identity=['G']; enemy.card.color_identity=['G']
    own.card.is_legendary=True
    card=_spell(name,ORACLE[name]); card.keywords={'Duel for Dominance':['Coven'],'Savage Punch':['Ferocious']}.get(name,[])
    spell=_hand(eng,card)
    assert parse_oracle(spell.card).modeled,name
    _cast(eng,spell,targets=[own,enemy])
    assert own.damage_marked==2
    assert enemy.damage_marked==own.power
    assert enemy.power==2
    assert enemy.counters.get('+1/+1',0)==0

def test_pair_pump_is_only_friendly_and_condition_does_not_gate_fight():
    for knight in (False,True):
        eng=_engine(); own=_bf(eng,_creature('Knight',3,20)); enemy=_bf(eng,_creature('Enemy',2,20),player='p2')
        if knight: own.card.type_line='Creature — Knight'
        _cast(eng,_hand(eng,_spell('Joust',ORACLE['Joust'])),targets=[own,enemy])
        assert own.power==(5 if knight else 3)
        assert enemy.damage_marked==own.power
        assert enemy.power==2

def test_reject_unknown_condition_or_extra_instruction():
    body="choose target creature you control and target creature you don't control. if you control a spaceship, the creature you control gets +1/+1 until end of turn. then those creatures fight each other."
    assert match_clause(body) is None
    assert match_clause(ORACLE['Joust'].lower()+" Draw a card.") is None

@pytest.mark.parametrize('quality',['host','augment','neither'])
def test_really_epic_permanent_buff_and_blink(quality):
    eng=_engine(); card=_creature('Creature',3,20)
    if quality=='host': card.type_line='Host Creature — Cat'
    if quality=='augment': card.keywords=['Augment']
    own=_bf(eng,card); enemy=_bf(eng,_creature('Enemy',2,20),player='p2')
    _cast(eng,_hand(eng,_spell('Really Epic Punch',ORACLE['Really Epic Punch'])),targets=[own,enemy])
    expected=5 if quality!='neither' else 3
    assert own.power==expected
    assert enemy.damage_marked==expected
    from mtg_analyzer.game import durations
    durations.sweep(eng.state,'cleanup')
    eng.rules.context.recompute()
    assert own.power==expected
    eng.rules.context.blink(own)
    eng.rules.context.recompute()
    assert own.power==3

@pytest.mark.parametrize('commander',[False,True])
def test_throne_monarch_only_for_own_commander(commander):
    eng=_engine(); own=_bf(eng,_creature('Friendly',4,20)); enemy=_bf(eng,_creature('Enemy',2,2),player='p2')
    if commander:
        general=_bf(eng,_creature('Commander',1,20)); general.is_commander=True
    card=_spell('Fight for the Throne',ORACLE['Fight for the Throne'])
    assert parse_oracle(card).modeled
    _cast(eng,_hand(eng,card),targets=[own,enemy])
    assert eng.state.monarch_id==('p1' if commander else None)


def _answer_target(eng,target=None):
    choice=eng.state.pending_choice
    assert choice and choice['kind']=='trigger_target',choice
    option=next(o for o in choice['options'] if o.get('instance_id')==getattr(target,'instance_id',None))
    eng.rules.resolve_choice(option['id']); eng.resolve_until_stable()

@pytest.mark.parametrize('own_power,enemy_power,expected',[(5,1,True),(1,8,False),(1,1,False)])
def test_rhino_only_enemy_excess_creates_fresh_artifact_target(own_power,enemy_power,expected):
    eng=_engine(); own=_bf(eng,_creature('Friendly',own_power,3)); enemy=_bf(eng,_creature('Enemy',enemy_power,3),player='p2')
    from mtg_analyzer.models.cards.card import Card
    artifact=_bf(eng,Card(id='trinket',name='Trinket',type_line='Artifact',converted_mana_cost=3),player='p2')
    card=_spell("Rhino's Rampage",ORACLE["Rhino's Rampage"])
    assert parse_oracle(card).modeled
    _cast(eng,_hand(eng,card),targets=[own,enemy])
    if expected:
        _answer_target(eng,artifact)
        assert artifact not in eng.state.permanents()
    else:
        assert eng.state.pending_choice is None
        assert artifact in eng.state.permanents()


def test_temur_all_modes_parse_and_fight_mode_executes():
    card=_spell('Temur Charm',ORACLE['Temur Charm']); card.keywords=[]
    assert parse_oracle(card).modeled
    eng=_engine(); own=_bf(eng,_creature('Friendly',3,20)); enemy=_bf(eng,_creature('Enemy',2,20),player='p2')
    obj=_hand(eng,card); eng.state.player_by_id('p1').mana_pool.add('C',4)
    eng.cast_spell(eng.state.player_by_id('p1'),obj,[own,enemy],mode=0); eng.resolve_until_stable()
    assert own.power==4 and enemy.damage_marked==4


def test_kraul_pumps_without_optional_target_and_declined_fight_keeps_pump():
    from mtg_analyzer.models.game.game_object import GameObject,Zone
    for pick in (False,True):
        eng=_engine(); player=eng.state.player_by_id('p1')
        dead=GameObject(_creature('Dead'),owner_id='p1',zone=Zone.GRAVEYARD); player.graveyard.append(dead)
        flyer=_bf(eng,_creature('Flyer',1,20,keywords=['Flying']),player='p2') if pick else None
        card=_creature('Kraul Harpooner',3,2,oracle_text=ORACLE['Kraul Harpooner'],keywords=['Reach','Undergrowth'],mana_cost_string='{1}')
        assert parse_oracle(card).modeled
        obj=_hand(eng,card); player.mana_pool.add('C',4)
        eng.cast_spell(player,obj); eng.resolve_until_stable()
        if flyer:
            _answer_target(eng,flyer)
        else:
            choice=eng.state.pending_choice
            if choice and choice['kind']=='trigger_target':
                decline=next(o for o in choice['options'] if not o.get('instance_id'))
                eng.rules.resolve_choice(decline['id']);eng.resolve_until_stable()
        assert obj.power==4
        choice=eng.state.pending_choice
        if choice:
            assert choice['kind']=='composite_optional',choice
            decline=next(o for o in choice['options'] if o['id']=='decline')
            eng.rules.resolve_choice(decline['id']);eng.resolve_until_stable()
        assert obj.power==4
        if flyer: assert flyer.damage_marked==0


def test_gimli_counts_resolutions_and_only_third_announces_fight():
    eng=_engine(); card=_creature('Gimli, Mournful Avenger',3,20,oracle_text=ORACLE['Gimli, Mournful Avenger'])
    assert parse_oracle(card).modeled
    gimli=_bf(eng,card); enemy=_bf(eng,_creature('Enemy',1,30),player='p2')
    for count in range(1,5):
        dead=_bf(eng,_creature('Victim'+str(count),1,1))
        eng.rules.destroy(dead); eng.resolve_until_stable()
        assert gimli.counters.get('+1/+1')==count
        if count==3: _answer_target(eng,enemy)
        else: assert eng.state.pending_choice is None
    assert enemy.damage_marked==6

@pytest.mark.parametrize('name', ['Blizzard Brawl','Duel for Dominance','Malamet Battle Glyph','Tail Swipe','Hog-Monkey Rampage','Savage Swipe','Ancient Animus'])
@pytest.mark.parametrize('positive',[False,True])
def test_each_friendly_condition_is_evaluated_before_buff(name,positive):
    eng=_engine(); power=2 if name=='Savage Swipe' else 4
    if name=='Savage Swipe' and not positive: power=3
    own=_bf(eng,_creature('Friendly',power,30)); enemy=_bf(eng,_creature('Enemy',1,30),player='p2')
    if name=='Blizzard Brawl':
        if positive:
            for i in range(3):
                snow=_creature('Snow'+str(i),1,20);snow.type_line='Snow Creature — Bear';_bf(eng,snow)
        buff=(1,0)
    elif name=='Duel for Dominance':
        if positive:
            _bf(eng,_creature('Small',1,20));_bf(eng,_creature('Medium',2,20))
        buff=(1,1)
    elif name=='Malamet Battle Glyph':
        own.turn_entered=eng.state.internal_turn.number if positive else -1;buff=(1,1)
    elif name=='Tail Swipe':
        eng.state.current_step='main1' if positive else 'upkeep';buff=(1,1)
    elif name=='Hog-Monkey Rampage':
        if not positive: own.card.power=3
        power=own.card.power;buff=(1,1)
    elif name=='Savage Swipe': buff=(2,2)
    else: own.card.is_legendary=positive;buff=(1,1)
    card=_spell(name,ORACLE[name]);card.keywords=['Coven'] if name=='Duel for Dominance' else []
    eng.rules.context.recompute()
    _cast(eng,_hand(eng,card),targets=[own,enemy])
    assert own.power==power+(buff[0] if positive else 0)
    assert enemy.damage_marked==own.power
    assert enemy.power==1


def _rhino_with_replacement_pause(players=2):
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.cards.card import Card
    eng=_engine() if players==2 else GameEngine.new_game([(f'p{i}',f'Player{i}',[]) for i in range(1,4)],starting_hand=0)
    eng.state.current_step='main1'
    own=_bf(eng,_creature('Friendly',4,30)); enemy=_bf(eng,_creature('Enemy',1,30),player='p2')
    for i in range(2):
        _bf(eng,Card(id='furnace'+str(i),name='Furnace of Rath',type_line='Enchantment'))
    artifact=_bf(eng,Card(id='trinket',name='Trinket',type_line='Artifact',converted_mana_cost=2),player='p2')
    _cast(eng,_hand(eng,_spell("Rhino's Rampage",ORACLE["Rhino's Rampage"])),targets=[own,enemy])
    assert eng.state.pending_choice and eng.state.pending_choice['kind']=='replacement_order'
    assert own.damage_marked==enemy.damage_marked==0
    return eng,own,enemy,artifact


def _drain_damage_choices(eng):
    for _ in range(10):
        choice=eng.state.pending_choice
        if not choice or choice['kind']!='replacement_order': return
        eng.rules.resolve_choice(choice['options'][0]['id']);eng.resolve_until_stable()
    pytest.fail('damage replacement did not finish')


def test_fight_damage_pause_clone_preserves_both_hits_and_batch():
    from mtg_analyzer.game.game_engine import GameEngine
    eng,own,enemy,artifact=_rhino_with_replacement_pause()
    clone=GameEngine(eng.state.clone())
    _drain_damage_choices(clone)
    assert clone.state.find_object(enemy.instance_id).damage_marked==20
    assert clone.state.find_object(own.instance_id).damage_marked==4
    assert own.damage_marked==enemy.damage_marked==0
    assert not clone.state._batch_hold
    assert clone.state.pending_choice is None # no excess on the 30-toughness enemy
    _drain_damage_choices(eng)
    assert enemy.damage_marked==20 and own.damage_marked==4


def test_pending_fight_affected_player_concession_releases_batch():
    eng,own,enemy,artifact=_rhino_with_replacement_pause(3)
    eng.rules.concede(eng.state.player_by_id('p2'))
    eng.resolve_until_stable()
    _drain_damage_choices(eng)
    assert not eng.state._batch_hold
    assert eng.state.pending_choice is None


def test_ace_sacrifices_before_reflexive_target_announcement():
    from mtg_analyzer.models.cards.card import Card
    eng=_engine(); card=_creature('Ace, Fearless Rebel',2,20,oracle_text=ORACLE['Ace, Fearless Rebel'],keywords=["Nitro-9", "Fight", "Doctor's companion"])
    assert parse_oracle(card).modeled
    ace=_bf(eng,card); enemy=_bf(eng,_creature('Enemy',1,20),player='p2')
    artifact=_bf(eng,Card(id='artifact',name='Artifact',type_line='Artifact'))
    eng.state.current_step='declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'),[ace]);eng.resolve_until_stable()
    choice=eng.state.pending_choice
    assert choice and choice['kind']=='pay_cost_then',choice
    assert ace.counters.get('+1/+1',0)==0
    eng.rules.resolve_choice(next(o['id'] for o in choice['options'] if o['id']!='decline'));eng.resolve_until_stable()
    choice=eng.state.pending_choice
    if choice and choice['kind']!='trigger_target':
        eng.rules.resolve_choice(next(o['id'] for o in choice['options'] if o.get('instance_id')==artifact.instance_id));eng.resolve_until_stable()
    assert artifact not in eng.state.permanents()
    assert ace.counters.get('+1/+1',0)==0
    _answer_target(eng,enemy)
    assert ace.counters.get('+1/+1')==1 and enemy.damage_marked==3


@pytest.mark.parametrize('name', ['Joust', "Ent's Fury"])
@pytest.mark.parametrize('missing', ['friendly', 'enemy'])
def test_illegal_first_requirement_does_not_promote_second(name, missing):
    eng = _engine()
    own = _bf(eng, _creature('Friendly', 3, 20))
    enemy = _bf(eng, _creature('Enemy', 2, 20), player='p2')
    spell = _hand(eng, _spell(name, ORACLE[name]))
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 4)
    eng.cast_spell(player, spell, target_groups=[[own], [enemy]])
    eng.rules.context.blink(own if missing == 'friendly' else enemy)
    eng.resolve_until_stable()
    assert own.power == (4 if name == "Ent's Fury" and missing == 'enemy' else 3)
    assert enemy.power == 2
    assert own.damage_marked == enemy.damage_marked == 0
    assert enemy.counters.get('+1/+1', 0) == 0


def test_fight_uses_both_powers_before_wither_changes_second_fighter():
    from mtg_analyzer.game.effects.core import FightEffect
    eng = _engine()
    own = _bf(eng, _creature('Wither fighter', 3, 20, keywords=['Wither']))
    enemy = _bf(eng, _creature('Enemy', 4, 20), player='p2')
    eng.rules.context.recompute()
    FightEffect(fighter_kind='creature_you_control', other_kind='creature_you_dont_control').apply(eng.rules.context, [own, enemy])
    assert enemy.counters.get('-1/-1') == 3
    assert own.damage_marked == 4


@pytest.mark.parametrize('shield', [False, True])
def test_rhino_counts_actual_enemy_damage_after_prevention(shield):
    from mtg_analyzer.models.cards.card import Card
    eng = _engine()
    own = _bf(eng, _creature('Friendly', 5, 20))
    enemy = _bf(eng, _creature('Enemy', 1, 3), player='p2')
    artifact = _bf(eng, Card(id='ring', name='Ring', type_line='Artifact', converted_mana_cost=1), player='p2')
    if shield:
        enemy.add_counters('shield', 1)
    _cast(eng, _hand(eng, _spell("Rhino's Rampage", ORACLE["Rhino's Rampage"])), targets=[own, enemy])
    if shield:
        assert eng.state.pending_choice is None
        assert artifact in eng.state.permanents()
        assert enemy.damage_marked == 0
    else:
        _answer_target(eng, artifact)
        assert artifact not in eng.state.permanents()


def test_pending_fight_choice_rewind_replays_both_hits_once():
    from mtg_analyzer.services.game_session import GameSession
    eng, own, enemy, artifact = _rhino_with_replacement_pause()
    session = GameSession(eng)
    choice = eng.state.pending_choice
    session.apply_action({'type': 'choose', 'option_id': choice['options'][0]['id']}, actor_id=choice['player_id'])
    session.rewind()
    restored = session.engine
    assert restored.state.pending_choice['kind'] == 'replacement_order'
    assert restored.state.find_object(own.instance_id).damage_marked == 0
    assert restored.state.find_object(enemy.instance_id).damage_marked == 0
    _drain_damage_choices(restored)
    assert restored.state.find_object(own.instance_id).damage_marked == 4
    assert restored.state.find_object(enemy.instance_id).damage_marked == 20
    assert not restored.state._batch_hold


def test_gimli_resolution_count_resets_for_new_turn():
    eng = _engine()
    gimli = _bf(eng, _creature('Gimli, Mournful Avenger', 3, 30, oracle_text=ORACLE['Gimli, Mournful Avenger']))
    enemy = _bf(eng, _creature('Enemy', 1, 40), player='p2')
    for turn in range(2):
        for count in range(1, 4):
            victim = _bf(eng, _creature(f'Victim {turn} {count}', 1, 1))
            eng.rules.destroy(victim)
            eng.resolve_until_stable()
            if count == 3:
                _answer_target(eng, enemy)
            else:
                assert eng.state.pending_choice is None
        eng.state.turn_nr += 1
    assert gimli.counters.get('+1/+1') == 6
    assert enemy.damage_marked == 15


def test_kraul_accepts_fight_after_source_pump():
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    eng = _engine()
    player = eng.state.player_by_id('p1')
    for index in range(2):
        player.graveyard.append(GameObject(_creature(f'Dead {index}'), owner_id='p1', zone=Zone.GRAVEYARD))
    flyer = _bf(eng, _creature('Flyer', 1, 20, keywords=['Flying']), player='p2')
    card = _creature('Kraul Harpooner', 3, 2, oracle_text=ORACLE['Kraul Harpooner'], keywords=['Reach', 'Undergrowth'], mana_cost_string='{1}')
    harpooner = _hand(eng, card)
    player.mana_pool.add('C', 4)
    eng.cast_spell(player, harpooner)
    eng.resolve_until_stable()
    _answer_target(eng, flyer)
    assert harpooner.power == 5
    choice = eng.state.pending_choice
    eng.rules.resolve_choice(next(o['id'] for o in choice['options'] if o['id'] != 'decline'))
    eng.resolve_until_stable()
    assert flyer.damage_marked == 5 and harpooner.damage_marked == 1


def test_kraul_optional_choice_does_not_fight_with_blinked_source():
    eng = _engine()
    player = eng.state.player_by_id('p1')
    flyer = _bf(eng, _creature('Flyer', 1, 20, keywords=['Flying']), player='p2')
    card = _creature('Kraul Harpooner', 3, 2, oracle_text=ORACLE['Kraul Harpooner'], keywords=['Reach', 'Undergrowth'], mana_cost_string='{1}')
    harpooner = _hand(eng, card)
    player.mana_pool.add('C', 4)
    eng.cast_spell(player, harpooner)
    eng.resolve_until_stable()
    _answer_target(eng, flyer)
    eng.rules.context.blink(harpooner)
    choice = eng.state.pending_choice
    eng.rules.resolve_choice(next(o['id'] for o in choice['options'] if o['id'] != 'decline'))
    eng.resolve_until_stable()
    assert flyer.damage_marked == harpooner.damage_marked == 0


@pytest.mark.parametrize('removed', [False, True])
def test_really_epic_counts_effective_granted_augment_and_ability_loss(removed):
    from mtg_analyzer.game.effects.core import GrantUntilEffect
    eng = _engine()
    own = _bf(eng, _creature('Ordinary', 3, 20, keywords=['Augment'] if removed else []))
    enemy = _bf(eng, _creature('Enemy', 1, 20), player='p2')
    if not removed:
        GrantUntilEffect(duration='rest_of_game', target_kind='creature', static={'type': 'grant_keyword', 'params': {'keywords': ['augment']}}).apply(eng.rules.context, [own])
    if removed:
        GrantUntilEffect(duration='rest_of_game', target_kind='creature', static={'type': 'remove_all_abilities', 'params': {}}).apply(eng.rules.context, [own])
    _cast(eng, _hand(eng, _spell('Really Epic Punch', ORACLE['Really Epic Punch'])), targets=[own, enemy])
    assert own.power == (3 if removed else 5)
    assert enemy.damage_marked == own.power


@pytest.mark.full_cache
@pytest.mark.parametrize('name, threshold', [('Hero of Oxid Ridge', 1), ('Mournwillow', 2)])
def test_newly_covered_power_limited_block_trigger_executes(name, threshold):
    from mtg_analyzer.services.card_database import CardDatabase
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.config import DB_PATH
    card = CardDatabase(DB_PATH).get_card(name)
    assert card is not None and parse_oracle(card).modeled
    eng = _engine()
    low = _bf(eng, _creature('Small blocker', threshold, 20), player='p2')
    high = _bf(eng, _creature('Large blocker', threshold + 1, 20), player='p2')
    if name == 'Mournwillow':
        from mtg_analyzer.models.cards.card import Card
        player = eng.state.player_by_id('p1')
        for kind in ('Artifact', 'Enchantment', 'Instant', 'Land'):
            player.graveyard.append(GameObject(Card(id=kind, name=kind, type_line=kind, is_instant=kind == 'Instant', is_land=kind == 'Land'), owner_id='p1', zone=Zone.GRAVEYARD))
        obj = _hand(eng, card)
        for color in ('C', 'B', 'G'):
            player.mana_pool.add(color, 5)
        eng.cast_spell(player, obj)
        eng.resolve_until_stable()
    else:
        hero = _bf(eng, card)
        eng.state.current_step = 'declare_attackers'
        eng.declare_attackers(eng.state.player_by_id('p1'), [hero])
        eng.resolve_until_stable()
    assert low.temp_cant_block
    assert not high.temp_cant_block


@pytest.mark.full_cache
@pytest.mark.parametrize('at_entry', [False, True])
def test_mournwillow_delirium_is_checked_at_entry_and_resolution(at_entry):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    eng = _engine()
    player = eng.state.player_by_id('p1')
    low = _bf(eng, _creature('Small blocker', 1, 20), player='p2')
    facts = [GameObject(Card(id=kind, name=kind, type_line=kind), owner_id='p1', zone=Zone.GRAVEYARD) for kind in ('Artifact', 'Enchantment', 'Instant', 'Land')]
    if at_entry:
        player.graveyard.extend(facts)
    obj = _hand(eng, CardDatabase(DB_PATH).get_card('Mournwillow'))
    for color in ('C', 'B', 'G'):
        player.mana_pool.add(color, 5)
    eng.cast_spell(player, obj)
    eng.rules.resolve_top_of_stack()
    if at_entry:
        assert len(eng.rules.pending_triggers) == 1
        player.graveyard.clear()
    else:
        assert not eng.rules.pending_triggers
        player.graveyard.extend(facts)
    eng.resolve_until_stable()
    assert not low.temp_cant_block


@pytest.mark.full_cache
def test_sacrificed_durable_handicraft_still_counters_its_creatures():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase
    eng = _engine()
    recipient = _bf(eng, _creature('Recipient', 2, 20))
    source = _bf(eng, CardDatabase(DB_PATH).get_card('Durable Handicraft'))
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('G', 6)
    eng.activate_ability(player, source, 0)
    assert source in player.graveyard
    eng.resolve_until_stable()
    assert recipient.counters.get('+1/+1') == 1


@pytest.mark.full_cache
def test_exalted_pumps_attacker_after_hierarch_leaves():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase
    eng = _engine()
    attacker = _bf(eng, _creature('Attacker', 2, 20))
    source = _bf(eng, CardDatabase(DB_PATH).get_card('Noble Hierarch'))
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [attacker])
    eng._fire_attacks_alone_event()  # The finished declaration emits this aggregate once.
    eng.rules.put_triggers_on_stack()
    eng.rules.exile(source)
    eng.resolve_until_stable()
    assert attacker.power == 3 and attacker.toughness == 21
