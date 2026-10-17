"""Source visits, exile visits and interactive returns of linked pools."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from test_mec106_gift import _engine, _bf, _creature

HAVEN = "{2}, {T}: Exile target creature you control.\nAt the beginning of your upkeep, you may sacrifice this land. If you do, return each card exiled with this land to the battlefield under its owner's control."


def _haven(eng):
    return _bf(eng, Card(id='haven', name='Safe Haven', type_line='Land', is_land=True, oracle_text=HAVEN))


def _store(eng, source, obj):
    source.tapped = False
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 2)
    eng.activate_ability(player, source, targets=[obj])
    eng.resolve_until_stable()
    assert obj.zone == Zone.EXILE


def _upkeep(eng, accept=True):
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice('do' if accept else 'decline')


def test_haven_returns_multiple_cards_to_owners_and_sacrifices_source():
    eng = _engine(); source = _haven(eng)
    first = _bf(eng, _creature('First'))
    second = _bf(eng, _creature('Stolen'), 'p2'); second.controller_id = 'p1'
    _store(eng, source, first); _store(eng, source, second)
    _upkeep(eng, False)
    assert source.zone == Zone.BATTLEFIELD and first.zone == Zone.EXILE
    _upkeep(eng)
    assert source.zone == Zone.GRAVEYARD
    assert first.zone == second.zone == Zone.BATTLEFIELD
    assert first.controller_id == 'p1' and second.controller_id == 'p2'


@pytest.mark.parametrize('failure', ['sacrifice_forbidden', 'control_changed', 'source_blinked'])
def test_haven_failed_sacrifice_keeps_cards_exiled(failure):
    eng = _engine(); source = _haven(eng); obj = _bf(eng, _creature('Stored'))
    _store(eng, source, obj)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.resolve_until_stable()
    if failure == 'sacrifice_forbidden': source.cant_be_sacrificed_this_turn = True
    elif failure == 'control_changed': source.controller_id = 'p2'
    else:
        eng.rules.exile(source); eng.rules.return_from_graveyard(source, 'battlefield')
    eng.resolve_pending_choice('do')
    assert obj.zone == Zone.EXILE and source.zone == Zone.BATTLEFIELD


def test_haven_never_returns_a_later_exile_visit():
    eng = _engine(); source = _haven(eng); obj = _bf(eng, _creature('Stored'))
    _store(eng, source, obj)
    eng.rules.return_to_hand(obj); eng.rules.exile(obj)
    _upkeep(eng)
    assert obj.zone == Zone.EXILE and source.zone == Zone.GRAVEYARD


def test_haven_copy_entry_pauses_and_clones_independently():
    eng = _engine(); source = _haven(eng); model = _bf(eng, _creature('Model', 3, 4))
    obj = _bf(eng, _creature('Clone', 0, 0, oracle_text=
        'You may have Clone enter as a copy of any creature on the battlefield.'))
    eng.rules.become_copy(obj, model)
    _store(eng, source, obj); _upkeep(eng)
    assert source.zone == Zone.GRAVEYARD and obj.zone == Zone.EXILE
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(model.instance_id))
    returned = clone.state.find_object(obj.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and returned.power == 3
    assert obj.zone == Zone.EXILE


RAZER = "When this creature enters, exile all lands.\nWhen this creature leaves the battlefield, return the exiled cards to the battlefield tapped under their owners' control."


def test_realm_razer_returns_only_its_original_exile_visits_tapped():
    eng = _engine()
    first = _bf(eng, Card(id='a', name='Plains', type_line='Basic Land — Plains', is_land=True))
    second = _bf(eng, Card(id='b', name='Island', type_line='Basic Land — Island', is_land=True), 'p2')
    source = _bf(eng, _creature('Realm Razer', 4, 2, oracle_text=RAZER))
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id))
    eng.resolve_until_stable()
    assert first.zone == second.zone == Zone.EXILE
    eng.rules.return_to_hand(first); eng.rules.exile(first)
    eng.rules.put_into_graveyard(source); eng.resolve_until_stable()
    assert first.zone == Zone.EXILE
    assert second.zone == Zone.BATTLEFIELD and second.tapped and second.controller_id == 'p2'


def test_old_source_activation_cannot_add_cards_to_new_haven_pool():
    eng = _engine(); source = _haven(eng); obj = _bf(eng, _creature('Stored'))
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 2)
    eng.activate_ability(player, source, targets=[obj])
    eng.rules.exile(source); eng.rules.return_from_graveyard(source, 'battlefield')
    eng.resolve_until_stable()
    assert obj.zone == Zone.EXILE
    _upkeep(eng)
    assert obj.zone == Zone.EXILE and source.zone == Zone.GRAVEYARD


def test_old_leave_trigger_returns_its_pool_without_consuming_new_source_pool():
    from mtg_analyzer.game.effects.exile_control import ExileEffect, ReturnAllExiledWithEffect
    eng = _engine(); source = _haven(eng)
    first = _bf(eng, _creature('First')); second = _bf(eng, _creature('Second'))
    original = source.zone_incarnation
    ExileEffect(source=source, track_exiled_with=True).apply(eng.rules.context, [first])
    eng.rules.exile(source); eng.rules.return_from_graveyard(source, 'battlefield')
    ExileEffect(source=source, track_exiled_with=True).apply(eng.rules.context, [second])
    eng.rules.context.resolving_source_incarnation = original
    ReturnAllExiledWithEffect(source=source).apply(eng.rules.context)
    eng.rules.context.resolving_source_incarnation = None
    assert first.zone == Zone.BATTLEFIELD and second.zone == Zone.EXILE
    assert source.exiled_with_ids == [second.instance_id]
    _upkeep(eng)
    assert second.zone == Zone.BATTLEFIELD


PURGATORY = 'Whenever a nontoken creature is put into your graveyard from the battlefield, exile that card.\nAt the beginning of your upkeep, you may pay {4} and 2 life. If you do, return a card exiled with this enchantment to the battlefield.'


def test_purgatory_stores_owned_deaths_and_returns_one_after_payment_and_selection():
    eng = _engine()
    source = _bf(eng, Card(id='purgatory', name='Purgatory', type_line='Enchantment',
                          oracle_text=PURGATORY))
    first = _bf(eng, _creature('First')); second = _bf(eng, _creature('Second'))
    second.controller_id = 'p2'  # "your graveyard" checks ownership.
    enemy = _bf(eng, _creature('Enemy'), 'p2')
    for obj in [first, second, enemy]:
        eng.rules.put_into_graveyard(obj); eng.resolve_until_stable()
    assert first.zone == second.zone == Zone.EXILE and enemy.zone == Zone.GRAVEYARD
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 4)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'pay_cost_then'
    eng.resolve_pending_choice('pay')
    assert player.life == 18
    assert eng.state.pending_choice['kind'] == 'choose_objects'
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(second.instance_id))
    assert clone.state.find_object(second.instance_id).zone == Zone.BATTLEFIELD
    assert clone.state.find_object(second.instance_id).controller_id == 'p1'
    assert clone.state.find_object(first.instance_id).zone == Zone.EXILE
    assert second.zone == Zone.EXILE


LIVIO = "{1}{W}: Choose another target creature. Its controller may exile it with an aegis counter on it.\n{2}{W}, {T}: Return all exiled cards with aegis counters on them to the battlefield under their owners' control.\nPartner (You can have two commanders if both have partner.)"


def test_livio_target_controller_decides_and_a_different_livio_can_return_global_pool():
    from mtg_analyzer.game.targeting import legal_targets
    eng = _engine()
    source = _bf(eng, _creature('Livio, Oathsworn Sentinel', oracle_text=LIVIO, keywords=['Partner']))
    other = _bf(eng, _creature('Livio, Oathsworn Sentinel', oracle_text=LIVIO, keywords=['Partner']), 'p2')
    target = _bf(eng, _creature('Enemy'), 'p2')
    spec = source.activated_abilities[0].effects[0].target_specs[0]
    offered = legal_targets(eng.state, 'p1', spec, source=source)
    assert source.instance_id not in {o['instance_id'] for o in offered}
    assert target.instance_id in {o['instance_id'] for o in offered}
    player = eng.state.player_by_id('p1'); player.mana_pool.add('W', 2)
    eng.activate_ability(player, source, targets=[target]); eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'pay_cost_then'
    assert eng.state.pending_choice['player_id'] == 'p2'
    eng.resolve_pending_choice('decline')
    assert target.zone == Zone.BATTLEFIELD
    player.mana_pool.add('W', 2)
    eng.activate_ability(player, source, targets=[target]); eng.resolve_until_stable()
    eng.resolve_pending_choice('pay')
    assert target.zone == Zone.EXILE and target.counters.get('aegis') == 1
    eng.rules.put_into_graveyard(source)
    player = eng.state.player_by_id('p2'); player.mana_pool.add('W', 3)
    eng.state.active_player_index = 1
    eng.activate_ability(player, other, ability_index=1); eng.resolve_until_stable()
    assert target.zone == Zone.BATTLEFIELD and target.controller_id == 'p2'
    assert 'aegis' not in target.counters


def test_purgatory_rejects_tokens_and_later_exile_visits_and_allows_declining_payment():
    eng = _engine()
    source = _bf(eng, Card(id='purgatory', name='Purgatory', type_line='Enchantment', oracle_text=PURGATORY))
    token = _bf(eng, _creature('Token')); token.is_token = True
    eng.rules.put_into_graveyard(token); eng.resolve_until_stable()
    assert not source.exiled_with_ids
    obj = _bf(eng, _creature('Stored'))
    eng.rules.put_into_graveyard(obj); eng.resolve_until_stable()
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 4)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.resolve_until_stable(); eng.resolve_pending_choice('decline')
    assert player.life == 20 and obj.zone == Zone.EXILE
    eng.rules.return_to_hand(obj); eng.rules.exile(obj)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.resolve_until_stable(); eng.resolve_pending_choice('pay')
    assert player.life == 18 and obj.zone == Zone.EXILE and eng.state.pending_choice is None


def test_livio_global_return_waits_for_clone_entry_and_ignores_cards_without_markers():
    from mtg_analyzer.game.effects.linked_pool_riders import ReturnExileCounterPoolEffect
    eng = _engine(); model = _bf(eng, _creature('Model', 3, 4))
    source = _bf(eng, _creature('Livio, Oathsworn Sentinel', oracle_text=LIVIO, keywords=['Partner']))
    obj = _bf(eng, _creature('Clone', 0, 0, oracle_text=
        'You may have Clone enter as a copy of any creature on the battlefield.'))
    eng.rules.become_copy(obj, model); eng.rules.exile(obj); obj.add_counters('aegis', 1)
    unmarked = _bf(eng, _creature('Unmarked')); eng.rules.exile(unmarked)
    ReturnExileCounterPoolEffect('aegis', source).apply(eng.rules.context)
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    clone = GameEngine(eng.state.clone()); clone.resolve_pending_choice(str(model.instance_id))
    assert clone.state.find_object(obj.instance_id).zone == Zone.BATTLEFIELD
    assert clone.state.find_object(unmarked.instance_id).zone == Zone.EXILE
    assert obj.zone == Zone.EXILE


def test_delayed_pool_return_captures_cards_before_spell_changes_zone():
    from test_mec106_gift import _hand, _spell
    eng = _engine(); obj = _bf(eng, _creature('Visitor'))
    spell = _hand(eng, _spell("Teferi's Time Twist", "Exile target permanent you control. Return that card to the battlefield under its owner's control at the beginning of the next end step. If it enters as a creature, it enters with an additional +1/+1 counter on it."))
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 1)
    eng.cast_spell(player, spell, targets=[obj]); eng.resolve_until_stable()
    assert spell.zone == Zone.GRAVEYARD and obj.zone == Zone.EXILE
    clone = GameEngine(eng.state.clone())
    clone._fire_delayed_triggers('end'); clone.resolve_until_stable()
    returned = clone.state.find_object(obj.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and returned.counters.get('+1/+1') == 1
    assert obj.zone == Zone.EXILE


def test_delayed_old_pool_capture_preserves_new_source_pool():
    from mtg_analyzer.game.effects.exile_control import ExileEffect, ReturnAllExiledWithEffect
    eng = _engine(); source = _haven(eng)
    first = _bf(eng, _creature('First')); second = _bf(eng, _creature('Second'))
    original = source.zone_incarnation
    ExileEffect(source=source, track_exiled_with=True).apply(eng.rules.context, [first])
    eng.rules.exile(source); eng.rules.return_from_graveyard(source, 'battlefield')
    ExileEffect(source=source, track_exiled_with=True).apply(eng.rules.context, [second])
    eng.rules.context.resolving_source_incarnation = original
    delayed = ReturnAllExiledWithEffect(source=source); delayed.capture_linked_pool(eng.rules.context)
    eng.rules.context.resolving_source_incarnation = None
    assert source.exiled_with_ids == [second.instance_id]
    delayed.apply(eng.rules.context)
    assert first.zone == Zone.BATTLEFIELD and second.zone == Zone.EXILE
    _upkeep(eng)
    assert second.zone == Zone.BATTLEFIELD
