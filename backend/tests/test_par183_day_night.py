"""PAR-183: global designation transitions and conditioned spell bodies."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

HEAD = 'Whenever day becomes night or night becomes day, '
ENTRY = "If it's neither day nor night, it becomes day as this creature enters.\n"


def engine():
    return GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0, starting_life=20)


def put(eng, name, text='', zone=Zone.BATTLEFIELD, owner='p1', toughness=3):
    card = Card(id=name, name=name, type_line='Creature', is_creature=True,
                oracle_text=text, power=2, toughness=toughness)
    obj = GameObject(card, owner_id=owner, controller_id=owner, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


@pytest.mark.parametrize('body', [
    'This creature deals 1 damage to each opponent.', 'Draw a card.',
    'Put a +1/+1 counter on target creature you control.',
    'You may pay {1}{R}. If you do, return this card from your graveyard to the battlefield tapped.',
    'Look at the top two cards of your library. Put one of them into your graveyard.',
    'You may tap or untap target nonland permanent.',
    'Discard up to two cards, then draw that many cards.',
    'Look at the top four cards of your library. You may reveal a creature card with mana value 3 or less '
    'from among them and put it into your hand. Put the rest on the bottom of your library in any order.',
])
def test_real_transition_body_shapes_are_modeled(body):
    result = parse_oracle(Card(id=body, name='Test', type_line='Creature', is_creature=True,
                               oracle_text=ENTRY + HEAD + body))
    assert result.modeled, result.unclaimed


@pytest.mark.parametrize('head', ['day becomes dusk', 'day becomes night and night becomes day',
                                  'a creature becomes day', 'day becomes night or dawn becomes day'])
def test_unrecognized_heads_fail_closed(head):
    assert not parse_oracle(Card(id=head, name='Test', type_line='Creature', is_creature=True,
                                 oracle_text=f'Whenever {head}, draw a card.')).modeled


def test_actual_untap_transitions_fire_once_and_initial_designation_does_not():
    eng = engine()
    put(eng, 'Brimstone Vandal', ENTRY + HEAD + 'This creature deals 1 damage to each opponent.')
    assert eng.state.day_night == 'day'
    assert not eng.rules.pending_triggers
    eng.state._last_turn_player_id = 'p2'
    eng.state._last_turn_spell_count = 0
    eng.rules.apply_day_night_turn_check()
    assert len(eng.rules.pending_triggers) == 1
    eng.rules.check_state_based_actions()
    assert len(eng.rules.pending_triggers) == 1
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 19
    eng.state._last_turn_spell_count = 2
    eng.rules.apply_day_night_turn_check()
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 18
    eng.rules.apply_day_night_turn_check()
    assert not eng.rules.pending_triggers


def test_single_direction_filters_and_effect_driven_changes():
    eng = engine()
    put(eng, 'Night watcher', 'Whenever night becomes day, this creature deals 1 damage to each opponent.')
    eng.rules.set_day_night('night')
    assert not eng.rules.pending_triggers
    eng.rules.set_day_night('day')
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 19
    eng.rules.set_day_night('night')
    assert not eng.rules.pending_triggers


@pytest.mark.parametrize('pay', [True, False])
def test_phoenix_triggers_in_graveyard_and_returns_tapped_only_if_paid(pay):
    eng = engine()
    phoenix = put(eng, 'Sunstreak Phoenix', 'Flying\n' + ENTRY + HEAD +
                  'You may pay {1}{R}. If you do, return this card from your graveyard to the battlefield tapped.',
                  zone=Zone.GRAVEYARD)
    eng.state.player_by_id('p1').mana_pool.add_many({'R': 1, 'C': 1})
    eng.rules.set_day_night('day')
    assert not eng.rules.pending_triggers
    eng.rules.set_day_night('night')
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice and choice['kind'] == 'pay_cost_then'
    selected = next(o for o in choice['options'] if (o['id'] != 'decline') == pay)
    eng.resolve_pending_choice(selected['id'])
    assert phoenix.zone == (Zone.BATTLEFIELD if pay else Zone.GRAVEYARD)
    if pay:
        assert phoenix.tapped
    assert not eng.rules.pending_triggers


@pytest.mark.parametrize('designation, damage', [('day', 2), ('night', 4), (None, 2)])
def test_wolf_strike_keeps_two_targets_and_uses_current_power(designation, damage):
    eng = engine()
    eng.state.day_night = designation
    wolf = put(eng, 'Wolf', toughness=10)
    victim = put(eng, 'Victim', owner='p2', toughness=10)
    spell_card = Card(id='wolf-strike', name='Wolf Strike', type_line='Instant', is_instant=True,
        oracle_text="Target creature you control gets +2/+0 until end of turn if it's night. "
                    "Then it deals damage equal to its power to target creature you don't control.")
    spell = GameObject(spell_card, owner_id='p1', controller_id='p1', zone=Zone.STACK)
    bind_from_catalogue(spell)
    assert len(spell.spell_effects) == 2
    eng.state.stack.append(StackItem(kind='spell', controller_id='p1', obj=spell,
                                    effects=spell.spell_effects, targets=[wolf, victim], target_groups=[[wolf], [victim]]))
    eng.rules.resolve_top_of_stack()
    assert victim.damage_marked == damage
    assert wolf.damage_marked == 0


def test_celestus_toggle_parses_and_emits_one_real_transition():
    eng = engine()
    obj = put(eng, 'The Celestus', "{3}, {T}: If it's night, it becomes day. Otherwise, it becomes night. "
              'Activate only as a sorcery.\n' + HEAD + 'You gain 1 life. You may draw a card. If you do, discard a card.')
    assert obj.activated_abilities
    assert parse_effect_body("it becomes twilight") is None
    ability = obj.activated_abilities[0]
    assert ability.cost.sorcery_speed_only
    eng.state.current_step = 'main1'
    obj.summoning_sick = False
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'C': 6})
    eng.activate_ability(player, obj)
    eng.resolve_until_stable()
    assert obj.tapped
    assert eng.state.day_night == 'night'
    assert not eng.rules.pending_triggers
    obj.tapped = False
    eng.activate_ability(player, obj)
    eng.resolve_until_stable()
    assert eng.state.day_night == 'day'
    assert player.life == 21
    choice = eng.state.pending_choice
    assert choice is not None  # optional draw is a separate resolution-time choice
    decline = next(o for o in choice['options'] if o['id'] == 'decline')
    eng.resolve_pending_choice(decline['id'])
    assert not eng.rules.pending_triggers


def test_nontransformable_daybound_does_not_loop_or_hide_later_permanents():
    eng = engine()
    obj = put(eng, 'Incomplete daybound', 'Daybound')
    eng.rules.set_day_night('night')
    assert eng.state.day_night == 'night'
    assert obj.card.name == 'Incomplete daybound'
    assert eng.rules._transform_mismatched_daynight_permanents() is False


def spell(eng, name, text, cost='{1}{B}', zone=Zone.HAND):
    card = Card(id=name, name=name, type_line='Instant', is_instant=True,
                oracle_text=text, mana_cost_string=cost)
    obj = GameObject(card, owner_id='p1', controller_id='p1', zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.HAND:
        eng.state.player_by_id('p1').add_to_zone(obj, zone)
    return obj


@pytest.mark.parametrize('designation, cost', [(None, 3), ('day', 3), ('night', 1)])
def test_moonrager_effective_cast_cost(designation, cost):
    eng = engine()
    eng.state.day_night = designation
    obj = spell(eng, "Moonrager's Slash", "This spell costs {2} less to cast if it's night.\n"
                'Deal 3 damage to any target.', cost='{2}{R}')
    assert eng.effective_cast_cost(eng.state.player_by_id('p1'), obj).converted_mana_cost == cost


@pytest.mark.parametrize('at_cast, at_resolution, power', [('day', 'night', 7), ('night', 'day', 18),
                                                         (None, None, 18)])
def test_olivia_checks_night_at_resolution_and_replaces_the_base_pump(at_cast, at_resolution, power):
    eng = engine()
    eng.state.day_night = at_cast
    victim = put(eng, 'Large creature', toughness=20)
    victim.card.power = 20
    obj = spell(eng, "Olivia's Midnight Ambush", 'Target creature gets -2/-2 until end of turn. '
                "If it's night, that creature gets -13/-13 until end of turn instead.", zone=Zone.STACK)
    eng.state.stack.append(StackItem(kind='spell', controller_id='p1', obj=obj,
                                    effects=obj.spell_effects, targets=[victim]))
    eng.state.day_night = at_resolution
    eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (power, power)


def test_day_transition_transforms_all_real_permanents_after_malformed_one():
    eng = engine()
    put(eng, 'Incomplete daybound', 'Daybound')
    wolves = []
    for name in ('First wolf', 'Second wolf'):
        card = Card(id=name, name=name, type_line='Creature', is_creature=True, power=2, toughness=2,
                    oracle_text='Daybound', layout='transform', back_name='Feral ' + name,
                    back_type_line='Creature', back_power=4, back_toughness=4, back_oracle_text='Nightbound')
        obj = GameObject(card, owner_id='p1', controller_id='p1', zone=Zone.BATTLEFIELD)
        bind_from_catalogue(obj)
        eng.state.add_to_battlefield(obj)
        wolves.append(obj)
    eng.rules.set_day_night('night')
    assert all(obj.transformed for obj in wolves)
    eng.rules.set_day_night('day')
    assert all(not obj.transformed for obj in wolves)
