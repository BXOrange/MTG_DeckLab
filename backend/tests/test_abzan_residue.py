"""Abzan's announced power budget and single two-target end-step trigger."""
import pytest

from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_abzan_armor_deck import _game, _card, _filler


def _reunion_setup(powers=(6, 4, 1)):
    engine = _game()
    player = engine.state.players[0]
    spell = _card(engine, 'Reunion of the House', zone=Zone.HAND)
    cards = [_filler(engine, f'Creature{i}', power=p, toughness=1, zone=Zone.GRAVEYARD) for i, p in enumerate(powers)]
    engine.state.current_step = 'main1'
    player.mana_pool.add_many({'W': 2, 'C': 5})
    return engine, player, spell, cards


@pytest.mark.parametrize('bad', ['over_budget', 'duplicate', 'foreign'])
def test_reunion_invalid_announced_targets_fail_before_mana_payment(bad):
    engine, player, spell, cards = _reunion_setup()
    chosen = cards if bad == 'over_budget' else [cards[0], cards[0]]
    if bad == 'foreign':
        chosen = [_filler(engine, 'Foreign', power=1, toughness=1, zone=Zone.GRAVEYARD, player='p2')]
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, targets=chosen)
    assert player.mana_pool.total() == 7 and spell.zone == Zone.HAND


@pytest.mark.parametrize('powers', [(), (0,) * 18, (-2, 12)])
def test_reunion_any_number_zero_and_negative_power_combinations(powers):
    engine, player, spell, cards = _reunion_setup(powers)
    engine.cast_spell(player, spell, targets=cards)
    assert not engine.state.pending_choice
    engine.resolve_until_stable()
    assert spell.zone == Zone.EXILE
    assert all(o.zone == Zone.BATTLEFIELD for o in cards)


def test_reunion_group_power_increase_invalidates_all_targets_and_self_exile():
    engine, player, spell, cards = _reunion_setup()
    engine.cast_spell(player, spell, targets=cards[:2])
    cards[0].card.power = 7
    engine.resolve_until_stable()
    assert all(o.zone == Zone.GRAVEYARD for o in cards)
    assert spell.zone == Zone.GRAVEYARD


def test_reunion_partial_zone_illegality_returns_other_target():
    engine, player, spell, cards = _reunion_setup()
    engine.cast_spell(player, spell, targets=cards[:2])
    engine.rules.exile(cards[0])
    engine.resolve_until_stable()
    assert cards[1].zone == Zone.BATTLEFIELD and cards[2].zone == Zone.GRAVEYARD
    assert spell.zone == Zone.EXILE


def _betor_setup(decline_first=False, decline_second=False):
    engine = _game()
    player = engine.state.players[0]
    betor = _card(engine, "Betor, Ancestor's Voice")
    ally = _filler(engine, 'Ally', power=1, toughness=1)
    fallen = _filler(engine, 'Fallen', mv=3, power=2, toughness=2, zone=Zone.GRAVEYARD)
    engine.rules.gain_life(player, 3)
    engine.rules.lose_life(player, 3)
    engine.state.current_step = 'end'
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id='p1', controller_id='p1'))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_choice('stop' if decline_first else str(ally.instance_id))
    engine.rules.resolve_choice('stop' if decline_second else str(fallen.instance_id))
    return engine, player, betor, ally, fallen


def test_betor_is_one_trigger_with_two_announced_targets_and_counter_stops_both():
    engine, player, betor, ally, fallen = _betor_setup()
    assert len(betor.triggered_abilities) == 1
    assert len(engine.state.stack) == 1
    assert engine.state.stack[0].target_groups == [[ally], [fallen]]
    engine.rules.counter_ability(engine.state.stack[0])
    engine.resolve_until_stable()
    assert not ally.counters and fallen.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('first,second', [(True, False), (False, True), (True, True)])
def test_betor_targets_are_independently_optional(first, second):
    engine, player, betor, ally, fallen = _betor_setup(first, second)
    engine.resolve_until_stable()
    assert ally.counters.get('+1/+1', 0) == (0 if first else 3)
    assert fallen.zone == (Zone.GRAVEYARD if second else Zone.BATTLEFIELD)


def test_betor_life_gain_is_measured_at_resolution_and_illegal_first_target_does_not_stop_return():
    engine, player, betor, ally, fallen = _betor_setup()
    ally.intrinsic_keywords.add('shroud')
    engine.rules.gain_life(player, 2)
    engine.resolve_until_stable()
    assert not ally.counters and fallen.zone == Zone.BATTLEFIELD


def test_betor_counters_use_life_gained_after_trigger_announcement():
    engine, player, betor, ally, fallen = _betor_setup()
    engine.rules.gain_life(player, 2)
    engine.resolve_until_stable()
    assert ally.counters.get('+1/+1') == 5 and fallen.zone == Zone.BATTLEFIELD


def test_reunion_copy_can_replace_six_four_with_seven_three_but_not_seven_five():
    engine, player, spell, cards = _reunion_setup((6, 4, 7, 3, 5))
    original = engine.cast_spell(player, spell, targets=cards[:2])
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    option = next(o for o in engine.state.pending_choice['options'] if o.get('instance_id') == cards[2].instance_id)
    engine.rules.resolve_choice(option['id'])
    options = engine.state.pending_choice['options']
    assert cards[4].instance_id not in {o.get('instance_id') for o in options}
    engine.rules.resolve_choice(next(o['id'] for o in options if o.get('instance_id') == cards[3].instance_id))
    assert copied.targets == cards[2:4] and original.targets == cards[:2]


def test_betor_with_both_targets_illegal_has_no_effects():
    engine, player, betor, ally, fallen = _betor_setup()
    ally.intrinsic_keywords.add('shroud')
    engine.rules.exile(fallen)
    engine.resolve_until_stable()
    assert not ally.counters and fallen.zone == Zone.EXILE and not engine.state.stack


def test_multiplayer_target_choices_leave_betors_one_ability_on_stack():
    from mtg_analyzer.services.game_session import GameSession, MULTIPLAYER

    engine, player, betor, ally, fallen = _betor_setup()
    engine.state.stack.clear()
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id='p1', controller_id='p1'))
    engine.rules.put_triggers_on_stack()
    session = GameSession(engine, mode=MULTIPLAYER, require_setup=False)
    session.apply_action({'type': 'choose', 'option_id': 'stop'})
    session.apply_action({'type': 'choose', 'option_id': str(fallen.instance_id)})
    assert len(session.engine.state.stack) == 1
    assert session.engine.state.stack[0].target_groups == [[], [fallen]]
    assert not ally.counters and fallen.zone == Zone.GRAVEYARD
    session.engine.rules.counter_ability(session.engine.state.stack[0])
    assert fallen.zone == Zone.GRAVEYARD
