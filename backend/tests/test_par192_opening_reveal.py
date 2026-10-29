"""PAR-192: post-mulligan reveals and independent delayed payoffs."""
import pytest
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.opening_hand import opening_hand_reveal_permission_line
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import step

NAMES = ('Chancellor of the Annex', 'Chancellor of the Dross', 'Chancellor of the Forge',
         'Chancellor of the Spires', 'Chancellor of the Tangle', 'Devourer of Destiny',
         'Providence', 'Sphinx of Foresight')

def _named(name):
    return CardDatabase(DB_PATH).get_card(name)

def _session(*hands, mulligan='none'):
    hands = hands + ((),) if len(hands) == 1 else hands
    forest = _named('Forest')
    eng = GameEngine.new_game([(f'p{i+1}', f'Player {i+1}', [forest]*30+[_named(n) for n in hand])
                               for i, hand in enumerate(hands)], starting_hand=7, starting_life=20)
    for player in eng.state.players:
        for obj in player.hand+player.library:
            bind_from_catalogue(obj)
    return GameSession(eng, require_setup=True, mulligan_style=mulligan)

def _keep(session):
    for player in session.engine.state.players:
        session.apply_action({'type':'keep_hand'}, actor_id=player.id)

def _choose(session, name=None, *, decline=False):
    choice = session.engine.state.pending_choice
    value = 'decline' if decline else next(o['id'] for o in choice['options'] if o['id']!='decline'
                    and (name is None or name in o['label']))
    session.apply_action({'type':'choose', 'option_id':value}, actor_id=choice['player_id'])

def _start(session):
    session.engine.advance_step()
    session.engine.advance_step()
    session.engine.resolve_until_stable()

@pytest.mark.parametrize('name', NAMES)
def test_all_eight_real_cards_are_fully_modeled(name):
    assert parse_oracle(_named(name)).modeled

@pytest.mark.parametrize('line', [
    'you may reveal this card from your opening hand. if you do, at the beginning of the first upkeep, draw a card and feed a goat.',
    'you may reveal this card from your opening hand. if you do, at the beginning of the second upkeep, draw a card.',
    'you may reveal this card from your opening hand. if you do, when an opponent casts a spell, draw a card.',
    'you may reveal this card from your opening hand. if you do, scry 3 at the beginning of your first upkeep and draw a card.',
])
def test_unsupported_bodies_or_timing_fail_closed(line):
    assert opening_hand_reveal_permission_line(line) is None

def test_reveal_only_after_all_keep_public_until_first_turn_and_payoff_once():
    s = _session(['Chancellor of the Forge'])
    s.apply_action({'type':'keep_hand'}, actor_id='p1')
    assert s.engine.state.pending_choice is None
    assert s.view('p2')['state']['players'][0]['hand']==[]
    s.apply_action({'type':'keep_hand'}, actor_id='p2')
    unseen=s.view('p2')['state']
    assert unseen['players'][0]['hand']==[]
    assert 'Chancellor' not in unseen['waiting_on_choice']['prompt']
    _choose(s)
    state=s.engine.state
    assert state.internal_turn.number==0
    for view in (s.view('p2'),s.observer_view()):
        assert [o['name'] for o in view['state']['players'][0]['hand']]==['Chancellor of the Forge']
    s.engine.advance_step()
    assert not state.opening_hand_revealed
    assert [o['name'] for o in s.view('p2')['state']['players'][0]['hand']]==['Chancellor of the Forge']
    assert len(state.delayed_triggers)==1
    s.engine.advance_step()
    s.engine.resolve_until_stable()
    assert len(state.battlefield)==1 and state.battlefield[0].is_token
    from mtg_analyzer.game.combat import has_haste
    assert has_haste(state.battlefield[0])
    step(s.engine,'upkeep')
    assert len(state.battlefield)==1

def test_decline_creates_no_delayed_payoff_or_reveal():
    s=_session(['Providence']);_keep(s);_choose(s,decline=True)
    assert not s.engine.state.delayed_triggers and not s.engine.state.opening_hand_revealed
    _start(s)
    assert s.engine.state.players[0].life==20

def test_multiple_actions_any_order_and_each_card_only_once():
    s=_session(['Chancellor of the Forge','Providence','Chancellor of the Forge']);_keep(s)
    _choose(s,'Providence')
    assert [dt.description for dt in s.engine.state.delayed_triggers]==['Providence']
    _choose(s,'Chancellor of the Forge');_choose(s,'Chancellor of the Forge')
    assert s.engine.state.pending_choice is None and len(s.engine.state.opening_hand_revealed)==3
    _start(s)
    assert len(s.engine.state.battlefield)==2 and s.engine.state.players[0].life==26

def test_queue_pending_card_and_delays_survive_session_undo_and_fresh_clone():
    s=_session(['Chancellor of the Forge','Providence']);_keep(s);_choose(s,'Providence')
    s.rewind()
    assert not s.engine.state.delayed_triggers and len(s.engine.state.opening_hand_queue)==2
    assert s.engine.state.pending_choice is not None
    _choose(s,'Chancellor of the Forge')
    assert len(s.engine.state.opening_hand_queue)==1
    clone=GameEngine(s.engine.state.clone());clone.resolve_pending_choice('reveal')
    assert len(clone.state.delayed_triggers)==2 and not clone.state.opening_hand_queue
    assert len(s.engine.state.delayed_triggers)==1

def test_london_bottomed_card_is_not_offered():
    s=_session(['Chancellor of the Forge'],mulligan='london');p=s.engine.state.players[0]
    source=next(o for o in p.hand if o.name=='Chancellor of the Forge')
    s._mulligan_counts['p1']=2
    s.apply_action({'type':'keep_hand','bottom_instance_ids':[source.instance_id]},actor_id='p1')
    s.apply_action({'type':'keep_hand'},actor_id='p2')
    assert s.engine.state.pending_choice is None and not s.engine.state.delayed_triggers
    assert source in p.library

def test_old_pending_reveal_does_not_apply_to_returned_hand_visit():
    s=_session(['Chancellor of the Forge']);_keep(s);p=s.engine.state.players[0]
    source=next(o for o in p.hand if o.name=='Chancellor of the Forge')
    s.engine.rules.discard_specific(source);s.engine.rules.return_to_hand(source);_choose(s)
    assert not s.engine.state.delayed_triggers and not s.engine.state.opening_hand_revealed

def test_providence_payoff_survives_revealed_card_leaving_hand():
    s=_session(['Providence']);_keep(s);_choose(s);p=s.engine.state.players[0]
    source=next(o for o in p.hand if o.name=='Providence')
    s.engine.rules.discard_specific(source);_start(s)
    assert source.zone==Zone.GRAVEYARD and s.engine.state.players[0].life==26

def test_dross_gains_only_life_actually_lost_by_each_opponent():
    s=_session(['Chancellor of the Dross'],[],[]);_keep(s);_choose(s);eng=s.engine
    from mtg_analyzer.game.effects.library import PlayerShieldEffect
    eng.state.players[1].player_effects.append(PlayerShieldEffect())
    _start(s)
    assert [p.life for p in eng.state.players]==[23,20,17]

def test_nonstarting_spires_mills_each_opponent_on_first_global_upkeep():
    s=_session([],['Chancellor of the Spires'],[]);_keep(s);_choose(s)
    before=[len(p.library) for p in s.engine.state.players];_start(s)
    assert [len(p.library) for p in s.engine.state.players]==[before[0]-7,before[1],before[2]-7]

def test_tangle_waits_for_controllers_first_main_even_if_postcombat():
    s=_session([],['Chancellor of the Tangle']);_keep(s);_choose(s);_start(s);eng=s.engine
    step(eng,'main1')
    assert not eng.state.players[1].mana_pool.pool['G']
    eng.state.active_player_index=1;step(eng,'main2',player='p2')
    assert eng.state.players[1].mana_pool.pool['G'] and not eng.state.delayed_triggers

def test_sphinx_waits_for_own_first_upkeep_and_scry_options_remain_private():
    s=_session([],['Sphinx of Foresight']);_keep(s);_choose(s);_start(s);eng=s.engine
    assert eng.state.pending_choice is None and len(eng.state.delayed_triggers)==1
    eng.state.active_player_index=1;step(eng,'upkeep',player='p2')
    choice=eng.state.pending_choice
    assert choice['kind']=='scry' and choice['player_id']=='p2' and len(choice['options'])==4
    assert s.view('p1')['state']['pending_choice'] is None and not eng.state.delayed_triggers

def test_annex_once_per_opponent_after_source_departure_and_clone():
    s=_session(['Chancellor of the Annex'],[],[]);_keep(s);_choose(s);eng=s.engine;p=eng.state.players[0]
    source=next(o for o in p.hand if o.name=='Chancellor of the Annex');eng.rules.discard_specific(source)
    eng=GameEngine(eng.state.clone());eng.advance_step()
    for pid,countered in [('p1',False),('p2',True),('p2',False),('p3',True)]:
        p=eng.state.player_by_id(pid);spell=GameObject(_named('Memnite'),owner_id=pid,zone=Zone.HAND)
        bind_from_catalogue(spell);p.add_to_zone(spell,Zone.HAND)
        eng.state.active_player_index=eng.state.players.index(p);eng.state.current_phase='main';eng.state.current_step='main1'
        eng.cast_spell(p,spell);eng.resolve_until_stable()
        if eng.state.pending_choice:
            eng.resolve_pending_choice('decline');eng.resolve_until_stable()
        assert spell.zone==(Zone.GRAVEYARD if countered else Zone.BATTLEFIELD)
    assert not eng.state.turn_scoped_triggers


def test_unrepresented_targeted_opening_payoff_fails_closed():
    line='you may reveal this card from your opening hand. if you do, at the beginning of the first upkeep, destroy target creature.'
    assert opening_hand_reveal_permission_line(line) is None


@pytest.mark.parametrize('keep_one',[False,True])
def test_devourer_setup_reveal_runs_optional_top_selection_and_exiles_the_rest(keep_one):
    s=_session(['Devourer of Destiny']);_keep(s);_choose(s);eng=s.engine
    player=eng.state.players[0]
    original=[o.instance_id for o in player.library[-4:]]
    _start(s)
    choice=eng.state.pending_choice
    assert choice['kind']=='choose_objects'
    option=next(o['id'] for o in choice['options'] if o['id']!='decline') if keep_one else 'decline'
    eng.resolve_pending_choice(option);eng.resolve_until_stable()
    assert len(player.exile)==(3 if keep_one else 4)
    assert set(o.instance_id for o in player.exile)<=set(original)
    if keep_one:
        assert player.library[-1].instance_id in original
    assert not eng.state.delayed_triggers


def test_mixed_caverns_permission_can_exile_a_queued_reveal_before_it_is_taken():
    s=_session([],['Chancellor of the Forge','Gemstone Caverns']);_keep(s)
    _choose(s,'Gemstone Caverns')
    assert s.engine.state.pending_choice['kind']=='choose_objects'
    _choose(s,'Chancellor of the Forge')
    assert s.engine.state.pending_choice is None and not s.engine.state.delayed_triggers
    assert not s.engine.state.opening_hand_queue
    assert any(o.name=='Chancellor of the Forge' for o in s.engine.state.players[1].exile)


def test_mixed_ogre_and_reveal_permissions_preserve_each_actions_consequence():
    s=_session(['Buried Ogre','Chancellor of the Forge']);_keep(s)
    _choose(s,'Chancellor of the Forge');_choose(s,'Buried Ogre')
    assert s.engine.state.players[0].life==19
    assert [o.name for o in s.engine.state.players[0].graveyard]==['Buried Ogre']
    assert len(s.engine.state.delayed_triggers)==1


def _annex_spell(eng,player_id,name='Memnite'):
    p=eng.state.player_by_id(player_id)
    spell=GameObject(_named(name),owner_id=player_id,zone=Zone.HAND)
    bind_from_catalogue(spell);p.add_to_zone(spell,Zone.HAND)
    eng.state.active_player_index=eng.state.players.index(p)
    eng.state.current_phase='main';eng.state.current_step='main1'
    eng.cast_spell(p,spell)
    return spell


def test_annex_first_spell_tax_can_be_paid_and_payment_choice_survives_clone():
    s=_session(['Chancellor of the Annex']);_keep(s);_choose(s);eng=s.engine;eng.advance_step()
    eng.state.players[1].mana_pool.add('C',1)
    spell=_annex_spell(eng,'p2');eng.resolve_until_stable()
    assert eng.state.pending_choice['kind']=='ward'
    clone=GameEngine(eng.state.clone());clone.resolve_pending_choice('pay');clone.resolve_until_stable()
    assert clone.state.find_object(spell.instance_id).zone==Zone.BATTLEFIELD
    assert clone.state.players[1].mana_pool.total()==0
    assert spell.zone==Zone.STACK


def test_annex_old_tax_does_not_counter_the_same_card_recast_as_a_new_spell():
    s=_session(['Chancellor of the Annex']);_keep(s);_choose(s);eng=s.engine;eng.advance_step()
    eng.state.players[1].mana_pool.add('U',2)
    spell=_annex_spell(eng,'p2',name='Spectral Sailor');eng.rules.put_triggers_on_stack()
    eng.rules.counter_spell(spell);eng.rules.return_to_hand(spell)
    eng.cast_spell(eng.state.players[1],spell)
    eng.resolve_until_stable()
    assert spell.zone==Zone.BATTLEFIELD and eng.state.pending_choice is None


def test_annex_battlefield_ability_still_taxes_later_opponent_spells():
    s=_session([]);_keep(s);eng=s.engine;eng.advance_step()
    source=GameObject(_named('Chancellor of the Annex'),owner_id='p1',zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source);eng.state.add_to_battlefield(source)
    for _ in range(2):
        spell=_annex_spell(eng,'p2');eng.resolve_until_stable()
        assert spell.zone==Zone.GRAVEYARD


def test_actual_devourer_cast_trigger_announces_only_a_colored_permanent():
    s=_session(['Devourer of Destiny']);_keep(s);_choose(s,decline=True);_start(s);eng=s.engine
    for name in ('Grizzly Bears','Forest'):
        obj=GameObject(_named(name),owner_id='p2',zone=Zone.BATTLEFIELD)
        bind_from_catalogue(obj);eng.state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()
    eng.state.current_phase='main';eng.state.current_step='main1'
    eng.state.players[0].mana_pool.add('C',7)
    source=next(o for o in eng.state.players[0].hand if o.name=='Devourer of Destiny')
    eng.cast_spell(eng.state.players[0],source);eng.resolve_until_stable()
    choice=eng.state.pending_choice
    assert choice['kind']=='trigger_target'
    assert any('Grizzly Bears' in o['label'] for o in choice['options'])
    assert not any('Forest' in o['label'] for o in choice['options'])
    pick=next(o['id'] for o in choice['options'] if 'Grizzly Bears' in o['label'])
    eng.resolve_pending_choice(pick);eng.resolve_until_stable()
    assert any(o.name=='Grizzly Bears' for o in eng.state.players[1].exile)
    assert source.zone==Zone.BATTLEFIELD


def test_unrepresented_source_bound_payoff_fails_closed():
    line='you may reveal this card from your opening hand. if you do, at the beginning of the first upkeep, shuffle it into your library and draw a card.'
    assert opening_hand_reveal_permission_line(line) is None


def test_actual_mulligan_replaces_the_hand_before_opening_permissions_are_offered(monkeypatch):
    s=_session(['Chancellor of the Forge'],mulligan='london')
    from mtg_analyzer.models.game.player import Player
    def put_reveal_on_bottom(player):
        player.library.sort(key=lambda obj: obj.name!='Chancellor of the Forge')
    monkeypatch.setattr(Player,'shuffle_library',put_reveal_on_bottom)
    s.apply_action({'type':'mulligan'},actor_id='p1')
    assert not any(o.name=='Chancellor of the Forge' for o in s.engine.state.players[0].hand)
    _keep(s)
    assert s.engine.state.pending_choice is None and not s.engine.state.delayed_triggers


def test_declining_remaining_actions_only_finishes_the_current_player():
    s=_session(['Chancellor of the Forge','Providence'],['Chancellor of the Spires'])
    _keep(s);_choose(s,decline=True)
    assert s.engine.state.pending_choice['player_id']=='p2'
    _choose(s)
    assert [dt.description for dt in s.engine.state.delayed_triggers]==['Chancellor of the Spires']


def test_interactive_multiplayer_undo_replays_last_reveal_and_enters_first_priority_window():
    from mtg_analyzer.services.game_session import GameSessionManager
    forest=_named('Forest')
    s=GameSessionManager().create_multiplayer([
        {'player_id':'p1','name':'A','library':[forest]*30+[_named('Chancellor of the Forge'),_named('Providence')]},
        {'player_id':'p2','name':'B','library':[forest]*30},
    ],mulligan_style='none',takebacks_per_player=2)
    _keep(s);_choose(s,'Chancellor of the Forge')
    assert s.engine.state.current_step==''
    assert len(s.engine.state.opening_hand_revealed)==1
    _choose(s,'Providence')
    assert s.engine.state.current_step=='upkeep' and s.engine.state.priority_player is not None
    # Restore the exact pre-last-choice snapshot, as multiplayer take-back
    # does after approval, with a new engine subscribed to the cloned state.
    label,state,cursor,actor=s._history[-1]
    s._restore(state,cursor)
    assert s.engine.state.current_step==''
    assert len(s.engine.state.opening_hand_queue)==1
    _choose(s,'Providence')
    assert s.engine.state.current_step=='upkeep' and s.engine.state.priority_player is not None
    assert not s.engine.state.opening_hand_queue


def test_bot_uses_multiple_reveals_with_dynamic_option_ids():
    from mtg_analyzer.services.bots import create_bot,run_bots
    s=_session([],['Chancellor of the Forge','Chancellor of the Dross']);_keep(s)
    bots={'p2':create_bot('greedy','p2')}
    run_bots(s,bots,max_actions=2)
    assert s.engine.state.pending_choice is None
    assert len(s.engine.state.delayed_triggers)==2
    assert len(s.engine.state.opening_hand_revealed)==2


def test_two_annex_reveals_tax_the_same_first_spell_independently():
    s=_session(['Chancellor of the Annex','Chancellor of the Annex']);_keep(s)
    _choose(s);_choose(s);eng=s.engine;eng.advance_step()
    eng.state.players[1].mana_pool.add('C',1)
    spell=_annex_spell(eng,'p2');eng.rules.put_triggers_on_stack()
    assert len(eng.state.stack)==3
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind']=='ward'
    eng.resolve_pending_choice('pay');eng.resolve_until_stable()
    assert spell.zone==Zone.GRAVEYARD and not eng.state.turn_scoped_triggers
