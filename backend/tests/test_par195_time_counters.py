"""PAR-195: actual counter removals in exile and generic time placement."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import filler
from tests.test_par118_exile_hand_time_counters import _engine, _put, _db_card, _creature

REMOVAL = ('Aeon Chronicler', 'Benalish Commander', 'Detritivore',
           'Dinosaurs on a Spaceship', 'Fungal Behemoth')

@pytest.mark.parametrize('name', REMOVAL)
def test_real_removal_cards_have_exile_scoped_specs(name):
    parsed = parse_oracle(_db_card(name))
    assert parsed.modeled, parsed.unclaimed
    specs = [s for s in parsed.specs if s.trigger and s.trigger.get('event') == 'COUNTER_REMOVED']
    assert len(specs) == 1
    assert specs[0].trigger['filter'] == {'kind': 'time', 'zone': 'exile'}

@pytest.mark.parametrize('body', ('put a time counter on ~', 'put 3 time counters on target artifact'))
def test_time_uses_existing_generic_counter_effect(body):
    [spec] = parse_effect_body(body)
    assert spec.type == 'add_counters' and spec.params['kind'] == 'time'

@pytest.mark.parametrize('zone,kind', ((Zone.HAND,'time'), (Zone.BATTLEFIELD,'time'), (Zone.EXILE,'charge')))
def test_wrong_zone_and_counter_kind_do_not_trigger(zone, kind):
    eng = _engine()
    obj = _put(eng, _db_card('Aeon Chronicler'), 'p1', zone)
    obj.add_counters(kind, 2)
    eng.rules.add_counters(obj, -1, kind)
    assert not eng.rules.pending_triggers

@pytest.mark.parametrize('count,requested', ((3,2), (2,9)))
def test_each_actual_removed_counter_triggers_once(count, requested):
    eng = _engine()
    obj = _put(eng, _db_card('Aeon Chronicler'), 'p1', Zone.EXILE)
    obj.add_counters('time', count)
    before = len(eng.state.player_by_id('p1').hand)
    eng.rules.add_counters(obj, -requested, 'time')
    assert sum(a.trigger_event == EventType.COUNTER_REMOVED for a,e in eng.rules.pending_triggers) == min(count, requested)
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.resolve_pending_choice('decline')
        eng.resolve_until_stable()
    assert len(eng.state.player_by_id('p1').hand) == before + min(count, requested)

@pytest.mark.parametrize('name,token,power,toughness', (
    ('Benalish Commander','Soldier',1,1), ('Dinosaurs on a Spaceship','Dinosaur',2,2)))
def test_real_token_payoffs(name, token, power, toughness):
    eng = _engine()
    obj = _put(eng, _db_card(name), 'p1', Zone.EXILE)
    obj.add_counters('time', 2)
    eng.rules.add_counters(obj, -1, 'time')
    eng.resolve_until_stable()
    [made] = [o for o in eng.state.battlefield if o.name == token]
    assert (made.power, made.toughness, made.controller_id) == (power,toughness,'p1')
    if token == 'Dinosaur':
        assert combat.has(made,'flying') and combat.has(made,'haste')

@pytest.mark.parametrize('name', ('Detritivore','Fungal Behemoth'))
def test_real_targeted_payoff_chooses_target_and_optional_decline(name):
    eng = _engine()
    obj = _put(eng, _db_card(name), 'p1', Zone.EXILE)
    obj.add_counters('time',2)
    target = filler(eng,'Target',type_line='Land' if name == 'Detritivore' else 'Creature',
                    power=None if name == 'Detritivore' else 2,
                    toughness=None if name == 'Detritivore' else 2)
    eng.rules.add_counters(obj,-1,'time')
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice(str(target.instance_id))
    eng.resolve_until_stable()
    if name == 'Detritivore':
        assert target.zone == Zone.GRAVEYARD
    else:
        assert target.counters.get('+1/+1') == 1
        eng.rules.add_counters(obj,-1,'time')
        eng.resolve_until_stable()
        # Optional body can be declined without changing the target.
        eng.resolve_pending_choice('decline')
        eng.resolve_until_stable()
        if eng.state.pending_choice:
            eng.resolve_pending_choice('decline')
        assert target.counters.get('+1/+1') == 1


def test_last_counter_has_no_cast_permission_until_cast_trigger_resolves_and_decline_expires():
    eng = _engine()
    obj = _put(eng,_db_card('Aeon Chronicler'),'p1',Zone.EXILE)
    obj.add_counters('time',1)
    eng.rules.add_counters(obj,-1,'time')
    assert obj.instance_id not in eng.state.free_cast_instance_ids
    assert len(eng.rules.pending_triggers) == 2
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'play_during_resolution'
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert obj.zone == Zone.EXILE and obj.instance_id not in eng.state.free_cast_instance_ids
    assert not obj.granted_suspend_haste


def test_non_suspend_time_card_does_not_receive_cast_permission():
    eng = _engine()
    obj = _put(eng,_creature('No suspend',2),'p1',Zone.EXILE)
    obj.add_counters('time',1)
    eng.rules.remove_suspend_time_counter(obj)
    eng.resolve_until_stable()
    assert not eng.state.free_cast_instance_ids and eng.state.pending_choice is None


def test_payoff_survives_source_departure_and_clone_is_independent():
    eng = _engine()
    obj = _put(eng,_db_card('Aeon Chronicler'),'p1',Zone.EXILE)
    obj.controller_id = 'p2'  # outside the battlefield the owner controls its ability
    obj.add_counters('time',2)
    eng.rules.add_counters(obj,-1,'time')
    assert eng.rules.pending_triggers[0][0].controller_id == 'p1'
    eng.rules.return_to_hand(obj)
    before = len(eng.state.player_by_id('p1').hand)
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id('p1').hand) == before+1


def test_upkeep_and_pending_cast_are_bound_to_original_exile_visit():
    eng = _engine()
    obj = _put(eng,_db_card('Dinosaurs on a Spaceship'),'p1',Zone.EXILE)
    obj.add_counters('time',2)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep'))
    eng.rules.return_to_hand(obj)
    eng.rules.exile(obj)
    obj.add_counters('time',3)
    eng.resolve_until_stable()
    assert obj.counters['time'] == 3
    eng.rules.add_counters(obj,-3,'time')
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'play_during_resolution'
    clone = GameEngine(eng.state.clone())
    clone_obj = clone.state.find_object(obj.instance_id)
    clone.rules.return_to_hand(clone_obj)
    clone.rules.exile(clone_obj)
    assert not clone._has_resolution_play_permission(clone.state.player_by_id('p1'),clone_obj)
    assert eng._has_resolution_play_permission(eng.state.player_by_id('p1'),obj)


def test_actual_fixed_suspend_special_action_upkeep_payoff_and_free_cast():
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    obj = _put(eng,_db_card('Dinosaurs on a Spaceship'),'p1',Zone.HAND)
    p1.mana_pool.add_many({'R':1,'W':1,'C':3})
    eng.suspend(p1,obj)
    assert obj.zone == Zone.EXILE and obj.counters['time'] == 4
    for remaining in (3,2,1,0):
        eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep'))
        eng.resolve_until_stable()
        assert obj.counters.get('time',0) == remaining
    assert eng.state.pending_choice['kind'] == 'play_during_resolution'
    eng.play_resolution_card(p1,obj)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD and combat.has(obj,'haste')
    assert len([o for o in eng.state.battlefield if o.name == 'Dinosaur']) == 4


def test_actual_alaundo_grants_only_last_counter_cast_not_suspend_and_clones():
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    alaundo = _put(eng,_db_card('Alaundo the Seer'),'p1',Zone.BATTLEFIELD)
    alaundo.summoning_sick = False
    obj = _put(eng,_creature('Granted cast',1),'p1',Zone.HAND)
    eng.activate_ability(p1,alaundo,0)
    eng.resolve_until_stable()
    eng.resolve_pending_choice(str(obj.instance_id))
    eng.resolve_until_stable()
    assert obj.zone == Zone.EXILE and obj.counters['time'] == 1
    assert not obj.granted_suspend
    clone = GameEngine(eng.state.clone())
    clone_obj = clone.state.find_object(obj.instance_id)
    clone.rules.add_counters(clone_obj,-1,'time')
    clone.resolve_until_stable()
    assert clone.state.pending_choice['kind'] == 'play_during_resolution'
    clone.resolve_pending_choice('decline')
    clone.rules.add_counters(clone_obj,1,'time')
    clone.rules.add_counters(clone_obj,-1,'time')
    clone.resolve_until_stable()
    assert clone.state.pending_choice['kind'] == 'play_during_resolution'
    clone.play_resolution_card(clone.state.player_by_id('p1'),clone_obj)
    clone.resolve_until_stable()
    assert clone_obj.zone == Zone.BATTLEFIELD and combat.has(clone_obj,'haste')
    clone._step_cleanup()
    assert not combat.has(clone_obj,'haste')
    assert obj.zone == Zone.EXILE and obj.counters['time'] == 1
    # The granted trigger is tied to the original visit.
    eng.rules.return_to_hand(obj)
    eng.rules.exile(obj)
    obj.add_counters('time',1)
    eng.rules.add_counters(obj,-1,'time')
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None


@pytest.mark.parametrize('name', ('Cursed Recording','Out of Time','Pardic Dragon','Rose Tyler','The War Doctor'))
def test_independent_compound_family_gaps_stay_fail_closed(name):
    assert not parse_oracle(_db_card(name)).modeled


def test_real_self_placement_triggers_and_wilfred_dynamic_inspection():
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    lava = _put(eng,_db_card('Lavacore Elemental'),'p1',Zone.BATTLEFIELD)
    golem = _put(eng,_db_card('Soultether Golem'),'p1',Zone.BATTLEFIELD)
    wilfred = _put(eng,_db_card('Wilfred Mott'),'p1',Zone.BATTLEFIELD)
    eng._apply_combat_damage([(eng.state.player_by_id('p2'),1,lava)])
    eng.resolve_until_stable()
    assert lava.counters.get('time') == 1
    newcomer = _put(eng,_creature('Newcomer',1),'p1',Zone.HAND)
    p1.mana_pool.add_many({'C':1})
    eng.cast_spell(p1,newcomer)
    eng.resolve_until_stable()
    assert golem.counters.get('time') == 1
    # Upkeep places Wilfred's counter before reading X; top instant is ineligible.
    before = len(p1.library)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep'))
    eng.resolve_until_stable()
    assert wilfred.counters.get('time') == 1
    if eng.state.pending_choice:
        eng.resolve_pending_choice('decline')
        eng.resolve_until_stable()
    assert len(p1.library) == before


def test_generic_self_placement_in_exile_respects_captured_source_visit():
    from mtg_analyzer.game.effects.core import AddCountersEffect
    eng = _engine()
    obj = _put(eng,_db_card('Aeon Chronicler'),'p1',Zone.EXILE)
    effect = AddCountersEffect(count=1,kind='time',source=obj)
    context = eng.rules.context
    context.resolving_source_incarnation = obj.zone_incarnation
    effect.apply(context)
    assert obj.counters.get('time') == 1
    eng.rules.return_to_hand(obj)
    eng.rules.exile(obj)
    effect.apply(context)
    assert obj.counters.get('time',0) == 0


@pytest.mark.parametrize('head', (
    'Whenever a time counter is removed from another card while it is exiled',
    'Whenever a time counter is removed from this card while it is in your graveyard',
    'Whenever one or more time counters are removed from this card while it is exiled'))
def test_nearby_unsupported_trigger_quantifiers_and_subjects_decline(head):
    from mtg_analyzer.models.cards.card import Card
    parsed = parse_oracle(Card(id='near',name='Near',type_line='Enchantment',oracle_text=head+', draw a card.'))
    assert not parsed.modeled


@pytest.mark.parametrize('bottom', (0,1))
def test_owner_can_order_payoff_and_last_counter_cast_either_way(bottom):
    eng = _engine()
    eng.state.interactive_ordering = True
    obj = _put(eng,_db_card('Aeon Chronicler'),'p1',Zone.EXILE)
    obj.add_counters('time',1)
    eng.rules.add_counters(obj,-1,'time')
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice['kind'] == 'order_triggers'
    eng.rules.resolve_choice(bottom)
    assert len(eng.state.stack) == 2
    assert obj.instance_id not in eng.state.free_cast_instance_ids
    before = len(eng.state.player_by_id('p1').hand)
    eng.rules.resolve_top_of_stack()
    if eng.state.pending_choice:
        assert eng.state.pending_choice['kind'] == 'play_during_resolution'
        assert len(eng.state.player_by_id('p1').hand) == before
        eng.resolve_pending_choice('decline')
        eng.resolve_until_stable()
    else:
        assert len(eng.state.player_by_id('p1').hand) == before+1
        eng.resolve_until_stable()
        assert eng.state.pending_choice['kind'] == 'play_during_resolution'
        eng.resolve_pending_choice('decline')
    assert len(eng.state.player_by_id('p1').hand) == before+1


def test_simultaneous_removal_triggers_are_placed_in_apnap_order():
    eng = _engine()
    for owner in ('p2','p1'):
        obj = _put(eng,_db_card('Benalish Commander'),owner,Zone.EXILE)
        obj.add_counters('time',1)
        eng.rules.add_counters(obj,-1,'time')
    assert eng.rules.put_triggers_on_stack() == 4
    assert [item.controller_id for item in eng.state.stack] == ['p1','p1','p2','p2']


@pytest.mark.parametrize('name,color,fixed', (
    ('Aeon Chronicler','U',3), ('Benalish Commander','W',0),
    ('Detritivore','R',3), ('Fungal Behemoth','G',0)))
def test_actual_x_suspend_payment_upkeep_payoff_and_cast(name,color,fixed):
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    obj = _put(eng,_db_card(name),'p1',Zone.HAND)
    colors = 2 if name in ('Benalish Commander','Fungal Behemoth') else 1
    p1.mana_pool.add_many({color:colors,'C':fixed+2})
    target = filler(eng,'Payoff target',player='p2' if name == 'Detritivore' else 'p1',type_line='Land' if name == 'Detritivore' else 'Creature',
                    power=None if name == 'Detritivore' else 2,
                    toughness=None if name == 'Detritivore' else 2)
    if name == 'Fungal Behemoth':
        target.add_counters('+1/+1',1)
    params = obj.parametric_keywords['suspend']
    assert params == {'n':'X','cost':_db_card(name).oracle_text.split('Suspend X—')[1].split('.')[0], 'min_x':1}
    actions = [a for a in eng.legal_actions(p1) if a['type'] == 'suspend' and a['instance_id'] == obj.instance_id]
    assert len(actions) == 1 and actions[0]['has_x'] and actions[0]['min_x'] == 1 and actions[0]['max_x'] == 2
    before = p1.mana_pool.total()
    for invalid in (0,-1,20):
        with pytest.raises(ValueError):
            eng.suspend(p1,obj,x=invalid)
        assert obj.zone == Zone.HAND and p1.mana_pool.total() == before
    eng.suspend(p1,obj,x=2)
    assert obj.zone == Zone.EXILE and obj.counters['time'] == 2
    assert p1.mana_pool.total() == 0
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep'))
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.resolve_pending_choice(str(target.instance_id))
        eng.resolve_until_stable()
    assert obj.counters['time'] == 1
    if name == 'Aeon Chronicler':
        assert len(p1.hand) == 1
    elif name == 'Benalish Commander':
        assert len([o for o in eng.state.battlefield if o.name == 'Soldier']) == 1
    elif name == 'Detritivore':
        assert target.zone == Zone.GRAVEYARD
        target = filler(eng,'Second nonbasic',player='p2',type_line='Land')
    else:
        assert target.counters['+1/+1'] == 2
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep'))
    eng.resolve_until_stable()
    if eng.state.pending_choice['kind'] == 'trigger_target':
        eng.resolve_pending_choice(str(target.instance_id))
        eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'play_during_resolution'
    eng.play_resolution_card(p1,obj)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD and combat.has(obj,'haste')


def test_session_suspend_action_threads_chosen_x():
    from mtg_analyzer.services.game_session import GameSession
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    obj = _put(eng,_db_card('Aeon Chronicler'),'p1',Zone.HAND)
    p1.mana_pool.add_many({'U':1,'C':6})
    session = GameSession(eng,require_setup=False)
    session.apply_action({'type':'suspend','instance_id':obj.instance_id,'x':3})
    assert obj.zone == Zone.EXILE and obj.counters['time'] == 3
    assert p1.mana_pool.total() == 0


def test_x_suspend_offer_and_payment_use_untapped_mana_sources():
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    obj = _put(eng,_db_card('Fungal Behemoth'),'p1',Zone.HAND)
    lands = [_put(eng,_db_card('Forest'),'p1',Zone.BATTLEFIELD) for _ in range(4)]
    [action] = [a for a in eng.legal_actions(p1) if a['type'] == 'suspend']
    assert action['max_x'] == 2 and action['auto_tap']
    eng.suspend(p1,obj,x=2)
    assert obj.zone == Zone.EXILE and obj.counters['time'] == 2
    assert all(land.tapped for land in lands) and p1.mana_pool.total() == 0


def test_zero_x_is_allowed_only_without_the_printed_nonzero_restriction():
    from mtg_analyzer.models.cards.card import Card
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    printed = Card(id='zero',name='Zero',type_line='Creature',is_creature=True,power=1,toughness=1,
                   oracle_text='Suspend X—{X}{U}',keywords=['Suspend'])
    obj = _put(eng,printed,'p1',Zone.HAND)
    assert obj.parametric_keywords['suspend']['min_x'] == 0
    p1.mana_pool.add_many({'U':1})
    eng.suspend(p1,obj,x=0)
    assert obj.zone == Zone.EXILE and obj.counters.get('time',0) == 0
    assert not eng.rules.pending_triggers


def test_zone_change_counter_reset_and_removing_zero_do_not_emit_removal_payoff():
    eng = _engine()
    obj = _put(eng,_db_card('Aeon Chronicler'),'p1',Zone.EXILE)
    obj.add_counters('time',2)
    eng.rules.return_to_hand(obj)
    eng.rules.exile(obj)
    eng.rules.add_counters(obj,-3,'time')
    assert not eng.rules.pending_triggers


def _cast_dinosaurs_via_last_counter(eng):
    obj = _put(eng,_db_card('Dinosaurs on a Spaceship'),'p1',Zone.EXILE)
    obj.add_counters('time',1)
    eng.rules.add_counters(obj,-1,'time')
    eng.resolve_until_stable()
    eng.play_resolution_card(eng.state.player_by_id('p1'),obj)
    return obj


def test_intrinsic_suspend_haste_persists_cleanup_and_ends_permanently_on_control_loss():
    from mtg_analyzer.game.control import gain_control
    eng = _engine()
    obj = _cast_dinosaurs_via_last_counter(eng)
    eng.resolve_until_stable()
    assert combat.has(obj,'haste')
    eng._step_cleanup()
    assert combat.has(obj,'haste')
    eng.state.internal_turn.number += 1
    eng.recompute_continuous_effects()
    assert combat.has(obj,'haste')
    gain_control(eng.state,obj,'p2')
    eng.recompute_continuous_effects()
    assert not combat.has(obj,'haste')
    gain_control(eng.state,obj,'p1')
    eng.recompute_continuous_effects()
    assert not combat.has(obj,'haste')


def test_intrinsic_suspend_haste_does_not_follow_a_later_battlefield_visit():
    eng = _engine()
    obj = _cast_dinosaurs_via_last_counter(eng)
    eng.resolve_until_stable()
    assert combat.has(obj,'haste')
    eng.rules.return_to_hand(obj)
    eng.state.player_by_id('p1').hand.remove(obj)
    eng.state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()
    assert not combat.has(obj,'haste')


def test_losing_spell_control_ends_intrinsic_suspend_haste_even_if_control_returns():
    eng = _engine()
    obj = _cast_dinosaurs_via_last_counter(eng)
    item = next(item for item in eng.state.stack if item.obj is obj)
    assert obj.granted_suspend_haste['duration'] == 'until_control_lost'
    eng.rules.gain_control_of_spell(item,'p2')
    eng.rules.gain_control_of_spell(item,'p1')
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD and not combat.has(obj,'haste')


@pytest.mark.parametrize('humility_first',(True,False))
def test_suspend_haste_uses_cast_grant_timestamp_against_humility(humility_first):
    eng = _engine()
    if humility_first:
        _put(eng,_db_card('Humility'),'p1',Zone.BATTLEFIELD)
    obj = _cast_dinosaurs_via_last_counter(eng)
    if not humility_first:
        _put(eng,_db_card('Humility'),'p1',Zone.BATTLEFIELD)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert combat.has(obj,'haste') is humility_first


def test_granted_suspend_ends_when_its_exile_visit_ends():
    eng = _engine()
    obj = _put(eng,_creature('Granted suspend',2),'p1',Zone.EXILE)
    obj.granted_suspend = True
    obj.add_counters('time',2)
    eng.rules.return_to_hand(obj)
    eng.rules.exile(obj)
    obj.add_counters('time',2)
    assert not obj.granted_suspend
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='upkeep'))
    eng.resolve_until_stable()
    assert obj.counters['time'] == 2 and not eng.rules.pending_triggers


def test_exiled_creature_card_is_not_a_creature_permanent_for_roaming_throne():
    eng = _engine()
    throne = _put(eng,_db_card('Roaming Throne'),'p1',Zone.BATTLEFIELD)
    throne.chosen_type = 'Avatar'
    obj = _put(eng,_db_card('Aeon Chronicler'),'p1',Zone.EXILE)
    obj.add_counters('time',2)
    eng.recompute_continuous_effects()
    eng.rules.add_counters(obj,-1,'time')
    assert len(eng.rules.pending_triggers) == 1
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id('p1').hand) == 1
