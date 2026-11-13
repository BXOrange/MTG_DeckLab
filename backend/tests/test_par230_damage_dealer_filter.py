"""Dealer history is a shared object qualifier, distinct from received damage."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import parse_object_phrase
from mtg_analyzer.parser.oracle.gate import parse_oracle


def game():
    return GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', []), ('p3', 'Carol', [])], starting_hand=0)


def put(eng, name, text='', player='p1', kind='Creature', zone=Zone.BATTLEFIELD):
    card = Card(id=name, name=name, oracle_text=text, type_line=kind,
                is_creature='Creature' in kind, is_instant='Instant' in kind,
                power=4 if 'Creature' in kind else None, toughness=6 if 'Creature' in kind else None)
    result = GameObject(card, owner_id=player, zone=zone)
    result.summoning_sick = False
    bind_from_catalogue(result)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(result)
    else:
        eng.state.player_by_id(player).add_to_zone(result, zone)
    return result


@pytest.mark.parametrize('phrase,expected,scope', [
    ('creature that dealt damage this turn', {'card_type': 'creature', 'dealt_damage_this_turn': 'any'}, None),
    ('creatures that dealt damage to you this turn', {'card_type': 'creature', 'dealt_damage_this_turn': 'you'}, None),
    ('red creature an opponent controls that dealt damage this turn',
     {'color': 'R', 'card_type': 'creature', 'dealt_damage_this_turn': 'any'}, 'not_you'),
    ('creature with flying that dealt damage to you this turn',
     {'card_type': 'creature', 'keyword': 'flying', 'dealt_damage_this_turn': 'you'}, None),
])
def test_qualifier_composes_with_characteristics(phrase, expected, scope):
    parsed = parse_object_phrase(phrase, plural=phrase.startswith('creatures'))
    assert parsed == (expected, scope)


@pytest.mark.parametrize('phrase', [
    'creature that dealt damage last turn',
    'creature that dealt damage to an opponent this turn',
    'creature that dealt damage to you this turn unless you paid {1}',
    'creature that dealt combat damage to you this turn',
])
def test_unknown_history_restrictions_are_not_dropped(phrase):
    assert parse_object_phrase(phrase) is None


@pytest.mark.parametrize('combat_damage', [True, False])
def test_dealer_and_recipient_and_player_scope_are_distinct(combat_damage):
    eng = game()
    source = put(eng, 'Reference', kind='Artifact')
    dealer = put(eng, 'Dealer', player='p2')
    recipient = put(eng, 'Recipient')
    eng.rules.deal_damage(recipient, 1, source=dealer, combat=combat_damage)
    assert combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'any'}, source, eng.state)
    assert not combat.matches_object_filter(recipient, {'dealt_damage_this_turn': 'any'}, source, eng.state)
    assert not combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'you'}, source, eng.state)
    eng.rules.deal_damage(eng.state.player_by_id('p3'), 1, source=dealer, combat=combat_damage)
    assert not combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'you'}, source, eng.state)
    eng.rules.deal_damage(eng.state.player_by_id('p1'), 1, source=dealer, combat=combat_damage)
    assert combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'you'}, source, eng.state)
    # Stealing a dealer does not erase damage history.
    dealer.controller_id = 'p1'
    assert combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'you'}, source, eng.state)
    # A later visit of the same tracked instance does erase its eligibility.
    eng.rules.exile(dealer)
    eng.state.player_by_id(dealer.owner_id).exile.remove(dealer)
    eng.state.add_to_battlefield(dealer)
    assert not combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'any'}, source, eng.state)


def test_zero_and_prevented_damage_do_not_qualify():
    from mtg_analyzer.game.effects.core import PreventDamageEffect
    eng = game()
    dealer = put(eng, 'Dealer')
    victim = put(eng, 'Victim', player='p2')
    eng.rules.deal_damage(victim, 0, source=dealer)
    assert not combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'any'}, state=eng.state)
    from mtg_analyzer.game.effects.core import GameContext
    PreventDamageEffect(amount='all', target_kind='creature').apply(GameContext(eng.state, eng.rules), [victim])
    eng.rules.deal_damage(victim, 1, source=dealer)
    assert not combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'any'}, state=eng.state)


@pytest.mark.parametrize('name,text,kind', [
    ('Spear of Heliod', 'Creatures you control get +1/+1.\n{1}{W}{W}, {T}: Destroy target creature that dealt damage to you this turn.', 'Artifact Enchantment'),
    ('Giltspire Avenger', 'Exalted\n{T}: Destroy target creature that dealt damage to you this turn.', 'Creature'),
    ('Avenging Arrow', 'Destroy target creature that dealt damage this turn.', 'Instant'),
    ('Reciprocate', 'Exile target creature that dealt damage to you this turn.', 'Instant'),
    ('Retaliate', 'Destroy all creatures that dealt damage to you this turn.', 'Instant'),
    ('Restore the Peace', "Return each creature that dealt damage this turn to its owner's hand.", 'Instant'),
    ("Executioner's Swing", 'Target creature that dealt damage this turn gets -5/-5 until end of turn.', 'Instant'),
])
def test_real_shapes_are_modeled(name, text, kind):
    card = Card(id=name, name=name, oracle_text=text, type_line=kind,
                is_creature='Creature' in kind, is_instant='Instant' in kind)
    assert parse_oracle(card).modeled


def test_spear_rejects_wrong_player_and_keeps_activating_player_after_control_change():
    eng = game()
    spear = put(eng, 'Spear of Heliod',
                'Creatures you control get +1/+1.\n{1}{W}{W}, {T}: Destroy target creature that dealt damage to you this turn.', kind='Artifact Enchantment')
    hit_you = put(eng, 'Hit Alice', player='p2')
    hit_other = put(eng, 'Hit Carol', player='p2')
    eng.rules.deal_damage(eng.state.player_by_id('p1'), 1, source=hit_you)
    eng.rules.deal_damage(eng.state.player_by_id('p3'), 1, source=hit_other)
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('W', 3)
    with pytest.raises(ValueError):
        eng.activate_ability(player, spear, targets=[hit_other])
    assert not spear.tapped and player.mana_pool.total() == 3
    eng.activate_ability(player, spear, targets=[hit_you])
    spear.controller_id = 'p3'
    eng.rules.resolve_top_of_stack()
    assert hit_you.zone == Zone.GRAVEYARD
    assert hit_other.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('name,text,expected', [
    ('Retaliate', 'Destroy all creatures that dealt damage to you this turn.', Zone.GRAVEYARD),
    ('Restore the Peace', "Return each creature that dealt damage this turn to its owner's hand.", Zone.HAND),
])
def test_group_filter_hits_only_qualifying_dealers(name, text, expected):
    eng = game()
    dealer = put(eng, 'Dealer', player='p2')
    untouched = put(eng, 'Untouched', player='p2')
    source = put(eng, name, text, kind='Instant', zone=Zone.HAND)
    eng.rules.deal_damage(eng.state.player_by_id('p1'), 1, source=dealer)
    eng.rules.cast_spell(eng.state.player_by_id('p1'), source)
    source.controller_id = 'p3'
    eng.rules.resolve_top_of_stack()
    assert dealer.zone == expected
    assert untouched.zone == Zone.BATTLEFIELD


def test_prior_turn_damage_and_unknown_filter_fail_closed():
    eng = game()
    dealer = put(eng, 'Dealer')
    eng.rules.deal_damage(eng.state.player_by_id('p2'), 1, source=dealer)
    assert combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'any'}, state=eng.state)
    eng.state.internal_turn.number += 1
    assert not combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'any'}, state=eng.state)
    assert not combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'bogus'}, state=eng.state)


def test_reciprocate_revalidates_after_target_returns_to_battlefield():
    eng = game()
    dealer = put(eng, 'Dealer', player='p2')
    spell = put(eng, 'Reciprocate', 'Exile target creature that dealt damage to you this turn.',
                kind='Instant', zone=Zone.HAND)
    eng.rules.deal_damage(eng.state.player_by_id('p1'), 1, source=dealer)
    eng.rules.cast_spell(eng.state.player_by_id('p1'), spell, targets=[dealer])
    eng.rules.exile(dealer)
    eng.state.player_by_id('p2').exile.remove(dealer)
    eng.state.add_to_battlefield(dealer)
    eng.rules.resolve_top_of_stack()
    assert dealer.zone == Zone.BATTLEFIELD
    assert spell.zone == Zone.GRAVEYARD


def test_departed_ability_does_not_credit_the_sources_new_visit():
    eng = game()
    dealer = put(eng, 'Dealer', '{0}: This creature deals 1 damage to any target.')
    eng.activate_ability(eng.state.player_by_id('p1'), dealer, targets=[eng.state.player_by_id('p2')])
    original_visit = dealer.zone_incarnation
    eng.rules.exile(dealer)
    eng.state.player_by_id('p1').exile.remove(dealer)
    eng.state.add_to_battlefield(dealer)
    eng.rules.resolve_top_of_stack()
    hits = [event for event in eng.state.events_this_turn() if event.type == 'DAMAGE']
    assert hits[-1].get('source_zone_incarnation') == original_visit
    assert not combat.matches_object_filter(dealer, {'dealt_damage_this_turn': 'any'}, state=eng.state)
