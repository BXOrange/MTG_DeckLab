"""PAR-212: shared object-state predicates and existing zone actions execute together."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.game.continuous import has_subtype
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature
from tests.test_par210_object_phrases import cast
from tests.test_par210_player_references import DB, board, game
from tests.test_par211_quantifier_scopes import multiplayer


@pytest.mark.parametrize('number,phrase,draws', [
    (0, 'no', True), (1, 'no', False), (3, 'fewer than 4', True),
    (4, 'fewer than 4', False), (4, 'exactly 4', True),
    (5, 'exactly 4', False), (5, '4 or more', True), (3, '4 or more', False),
])
def test_counter_threshold_uses_the_previous_object(number, phrase, draws):
    eng = game()
    victim = board(eng, creature('Victim', toughness=10))
    victim.counters['oil'] = number
    before = len(eng.state.players[0].hand)
    cast(eng, f'Tap target creature. If it has {phrase} oil counters on it, draw a card.', [victim])
    assert len(eng.state.players[0].hand) == before + draws


@pytest.mark.parametrize('own,second,third,draws', [(3, 2, 2, True), (2, 2, 1, False), (2, 1, 3, False)])
def test_count_is_compared_to_each_other_player_not_their_sum(own, second, third, draws):
    eng = multiplayer()
    for player, count in zip(eng.state.players, (own, second, third)):
        for n in range(count):
            board(eng, creature(f'{player.id}-{n}'), player.id)
    cast(eng, 'If you control more creatures than each other player, draw a card.')
    assert len(eng.state.players[0].hand) == draws


@pytest.mark.parametrize('chosen,expected', [('human', True), ('goblin', False)])
def test_condition_target_keeps_all_restrictions_and_gates_the_whole_body(chosen, expected):
    eng = game()
    victim = board(eng, creature('Human', type_line='Creature — Human'))
    victim.is_token = True
    victim.attacking = True
    card = Card(id='choice', name='Choice', type_line='Sorcery', is_sorcery=True, mana_cost_string='{0}',
                oracle_text='If target attacking creature token is the chosen type, put three +1/+1 counters on it and it gains deathtouch until end of turn.')
    assert parse_oracle(card).modeled
    spell = GameObject(card, owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    spell.chosen_type = chosen
    player = eng.state.players[0]
    player.hand.append(spell)
    eng.cast_spell(player, spell, targets=[victim])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert victim.counters.get('+1/+1', 0) == (3 if expected else 0)
    assert ('deathtouch' in victim.granted_keywords) == expected
    assert not spell.counters


def test_all_graveyards_moves_every_card_without_targets():
    eng = multiplayer()
    objects = []
    for p in eng.state.players:
        obj = GameObject(creature(p.name), owner_id=p.id, zone=Zone.GRAVEYARD)
        p.graveyard.append(obj)
        objects.append(obj)
    spell = cast(eng, 'Exile all graveyards.')
    assert all(o.zone == Zone.EXILE for o in objects)
    assert all(p.graveyard == ([spell] if p.id == 'p1' else []) for p in eng.state.players)
    assert not any(e.target_specs for e in spell.spell_effects)


@pytest.mark.parametrize('text,targeted', [
    ('Exile Operand Spell with 3 time counters on it.', False),
    ('Exile target creature with 2 egg counters on it.', True),
    ('Exile target Bear creature with 2 egg counters on it.', True),
    ('Tap target creature. Exile that creature with 2 egg counters on it.', True),
])
def test_exile_counter_rider_survives_zone_change(text, targeted):
    eng = game()
    victim = board(eng, creature('Victim')) if targeted else None
    if victim:
        victim.counters['charge'] = 4
    spell = cast(eng, text, [victim] if victim else [])
    obj = victim if victim else spell
    assert obj.zone == Zone.EXILE
    assert obj.counters == ({'egg': 2} if targeted else {'time': 3})


@pytest.mark.parametrize('name', ['Morningtide', 'Arc Blade', 'Inspiring Refrain', 'Reality Strobe', 'Adrestia', 'Getaway Car', 'Luxurious Locomotive'])
def test_real_cards_are_modeled(name):
    assert parse_oracle(DB.get_card(name)).modeled


@pytest.mark.parametrize('text', [
    'If target attacking creature token is the invented type, draw a card.',
    'If you control more imaginary objects than each other player, draw a card.',
    'If it has fewer than 0 oil counters on it, draw a card.',
    'Exile target creature with 3 time counters on it unless the moon is blue.',
    'Put target creature card from your graveyard onto your hand.',
])
def test_unsupported_conditions_and_destinations_remain_closed(text):
    assert not parse_oracle(creature('Unsupported', oracle_text=text)).modeled


def test_graveyard_put_destination_uses_the_existing_recursion_effect():
    eng = game()
    player = eng.state.players[0]
    victim = GameObject(creature('Dead'), owner_id=player.id, zone=Zone.GRAVEYARD)
    player.graveyard.append(victim)
    cast(eng, 'Put target creature card from your graveyard onto the battlefield.', [victim])
    assert victim.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('emerge', [False, True])
def test_adipose_offspring_pays_emerge_and_uses_sacrificed_toughness(emerge):
    eng = game()
    player = eng.state.players[0]
    victim = board(eng, creature('Sacrifice', power=3, toughness=5, cost='{3}'))
    card = DB.get_card('Adipose Offspring')
    assert parse_oracle(card).modeled
    spell = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    player.mana_pool.add_many({'W': 1, 'C': 3 if not emerge else 2})
    assert eng.can_cast(player, spell, alt_cost=emerge, sacrifice_choice=victim.instance_id if emerge else None)
    eng.cast_spell(player, spell, alt_cost=emerge, sacrifice_choice=victim.instance_id if emerge else None)
    eng.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD
    assert spell.emerge_cost_paid == emerge
    assert victim.zone == (Zone.GRAVEYARD if emerge else Zone.BATTLEFIELD)
    aliens = [o for o in eng.state.battlefield if o.is_token and o.card.name == 'Alien']
    assert len(aliens) == (5 if emerge else 1)
    assert player.mana_pool.total() == 0


def test_crew_type_is_remembered_when_the_creature_leaves_and_resets_next_turn():
    eng = game()
    vehicle = board(eng, DB.get_card('Adrestia'))
    assassin = board(eng, creature('Assassin', type_line='Creature — Human Assassin'))
    crew_index = next(i for i, a in enumerate(vehicle.activated_abilities) if a.cost.crew_power)
    eng.activate_ability(eng.state.players[0], vehicle, crew_index, tap_choices=[assassin.instance_id])
    eng.resolve_until_stable()
    eng.rules.put_into_graveyard(assassin)
    condition = {'kind': 'crewed_by_filter', 'selector': {'filter': {'subtype': 'assassin'}}}
    assert condition_holds(condition, eng.state, vehicle, 'p1')
    eng.state = eng.state.clone()
    vehicle = eng.state.find_object(vehicle.instance_id)
    assert condition_holds(condition, eng.state, vehicle, 'p1')
    eng.state.internal_turn.number += 1
    assert not condition_holds(condition, eng.state, vehicle, 'p1')


@pytest.mark.parametrize('subtype,draws', [('Assassin', True), ('Human', False)])
def test_adrestia_attack_uses_the_paid_crew_type(subtype, draws):
    eng = game()
    player = eng.state.players[0]
    vehicle = board(eng, DB.get_card('Adrestia'))
    pilot = board(eng, creature('Pilot', type_line=f'Creature — {subtype}'))
    crew_index = next(i for i, a in enumerate(vehicle.activated_abilities) if a.cost.crew_power)
    eng.activate_ability(player, vehicle, crew_index, tap_choices=[pilot.instance_id])
    eng.resolve_until_stable()
    eng.rules.put_into_graveyard(pilot)
    vehicle.summoning_sick = False
    eng.state.current_step = 'declare_attackers'
    before = len(player.hand)
    eng.declare_attackers(player, [vehicle])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert len(player.hand) == before + draws
    assert has_subtype(vehicle, 'assassin') == draws


@pytest.mark.parametrize('destination', ['into your hand', 'on the bottom of your library'])
def test_pronoun_zone_wording_uses_the_previous_pick(destination):
    eng = game()
    victim = board(eng, creature('Picked'))
    untouched = board(eng, creature('Untouched'))
    cast(eng, f'Tap target creature. Put it {destination}.', [victim])
    player = eng.state.players[0]
    assert victim.zone == (Zone.HAND if destination.startswith('into') else Zone.LIBRARY)
    assert victim in player.hand if victim.zone == Zone.HAND else player.library[0] is victim
    assert untouched.zone == Zone.BATTLEFIELD and not untouched.tapped


def test_emerge_checks_the_chosen_victim_and_preserves_colored_costs():
    eng = game()
    player = eng.state.players[0]
    expensive = board(eng, creature('Expensive', cost='{8}', toughness=7))
    cheap = board(eng, creature('Cheap', cost='{1}'))
    spell = GameObject(DB.get_card('Adipose Offspring'), owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    player.mana_pool.add('C', 10)
    assert not eng.can_cast(player, spell, alt_cost=True, sacrifice_choice=expensive.instance_id)

    player.mana_pool.empty()
    player.mana_pool.add('W', 1)
    assert eng.can_cast(player, spell, alt_cost=True, sacrifice_choice=expensive.instance_id)
    assert not eng.can_cast(player, spell, alt_cost=True, sacrifice_choice=cheap.instance_id)
    assert not eng.can_cast(player, spell, alt_cost=True, sacrifice_choice=-1)
    expensive.cant_be_sacrificed_this_turn = True
    assert not eng.can_cast(player, spell, alt_cost=True, sacrifice_choice=expensive.instance_id)


@pytest.mark.parametrize('counters,draws', [(0, False), (2, True)])
def test_destroyed_referent_uses_last_known_counters(counters, draws, monkeypatch):
    eng = game()
    victim = board(eng, creature('Bird', type_line='Creature — Bird'))
    victim.counters['oil'] = counters
    destroy = eng.rules.destroy
    def destroy_then_clear(*args, **kwargs):
        destroy(*args, **kwargs)
        victim.counters.clear()
    monkeypatch.setattr(eng.rules, 'destroy', destroy_then_clear)
    cast(eng, 'Destroy target creature. If it has 2 or more oil counters on it, draw a card.', [victim])
    assert victim.zone == Zone.GRAVEYARD and not victim.counters
    assert len(eng.state.players[0].hand) == draws


def test_emerge_legal_action_and_commander_tax_reuse_alternative_casting():
    eng = game()
    player = eng.state.players[0]
    victim = board(eng, creature('Victim', cost='{3}'))
    spell = GameObject(DB.get_card('Adipose Offspring'), owner_id='p1', zone=Zone.COMMAND)
    spell.is_commander = True
    bind_from_catalogue(spell)
    player.command.append(spell)
    player.commander_casts[spell.instance_id] = 2
    player.mana_pool.add_many({'W': 1, 'C': 6})
    assert eng.can_cast(player, spell, alt_cost=True, sacrifice_choice=victim.instance_id)
    eng.cast_spell(player, spell, alt_cost=True, sacrifice_choice=victim.instance_id)
    eng.resolve_until_stable()
    assert player.mana_pool.total() == 0
    assert spell.emerge_cost_paid


@pytest.mark.parametrize('matches', [False, True])
def test_sacrificed_ability_source_keeps_its_type_choice(matches):
    eng = game()
    source = board(eng, Card(id='choice-source', name='Choice Source', type_line='Enchantment',
        oracle_text='Sacrifice this enchantment: If target attacking creature token is the chosen type, put three +1/+1 counters on it and it gains deathtouch until end of turn.'))
    source.chosen_type = 'human' if matches else 'elf'
    victim = board(eng, creature('Human', type_line='Creature — Human'))
    victim.is_token = True
    victim.attacking = True
    eng.activate_ability(eng.state.players[0], source, 0, targets=[victim])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert source.zone == Zone.GRAVEYARD
    assert victim.counters.get('+1/+1', 0) == (3 if matches else 0)
    assert ('deathtouch' in victim.granted_keywords) == matches


def test_locomotive_counts_creatures_that_already_left_the_battlefield():
    eng = game()
    player = eng.state.players[0]
    vehicle = board(eng, DB.get_card('Luxurious Locomotive'))
    pilots = [board(eng, creature(f'Pilot {i}')) for i in range(2)]
    crew_index = next(i for i, a in enumerate(vehicle.activated_abilities) if a.cost.crew_power)
    eng.activate_ability(player, vehicle, crew_index, tap_choices=[p.instance_id for p in pilots])
    eng.resolve_until_stable()
    eng.rules.put_into_graveyard(pilots[0])
    vehicle.summoning_sick = False
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(player, [vehicle])
    eng.resolve_until_stable()
    treasures = [o for o in eng.state.battlefield if o.is_token and o.card.name == 'Treasure']
    assert len(treasures) == 2


def test_emerge_offer_uses_the_existing_cost_picker_and_submits_its_selection():
    eng = game()
    player = eng.state.players[0]
    pilot = board(eng, creature('Selected', cost='{3}', toughness=4))
    too_cheap = board(eng, creature('Unaffordable sacrifice', cost='{1}'))
    spell = GameObject(DB.get_card('Adipose Offspring'), owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    player.mana_pool.add_many({'W': 1, 'C': 2})
    offer = next(a for a in eng.legal_actions(player) if a.get('instance_id') == spell.instance_id and a.get('alt_cost'))
    assert offer['sacrifice_count_cost'] == {'count': 1, 'options': [{'instance_id': pilot.instance_id, 'name': pilot.name}]}
    eng.cast_spell(player, spell, alt_cost=True, sacrifice_choices=[pilot.instance_id])
    eng.resolve_until_stable()
    assert pilot.zone == Zone.GRAVEYARD and too_cheap.zone == Zone.BATTLEFIELD
    assert spell.emerge_cost_paid


@pytest.mark.parametrize('chosen,holds', [('creature', True), ('bear', True), ('artifact', False)])
def test_chosen_type_predicate_accepts_card_types_and_creature_subtypes(chosen, holds):
    eng = game()
    source = board(eng, creature('Choice source'))
    subject = board(eng, creature('Bear'))
    source.chosen_type = chosen
    assert condition_holds({'kind': 'is_chosen_type', 'of': 'affected'}, eng.state,
                           source, 'p1', subject) == holds


@pytest.mark.parametrize('type_line,holds', [('Creature — Elf', True), ('Artifact Creature — Golem', True), ('Creature — Bear', False)])
def test_condition_target_compound_predicate_tests_the_same_target(type_line, holds):
    eng = game()
    victim = board(eng, creature('Victim', type_line=type_line))
    cast(eng, 'If target creature is an artifact or elf, draw a card.', [victim])
    assert len(eng.state.players[0].hand) == holds


@pytest.mark.parametrize('counters,searches', [(2, False), (3, True), (4, False)])
def test_ayara_counter_intervening_if_gates_the_entire_trigger(counters, searches):
    eng = game()
    source = board(eng, DB.get_card("Ayara's Oathsworn"))
    source.counters['+1/+1'] = counters
    eng.recompute_continuous_effects()
    eng.rules.deal_damage(eng.state.players[1], 1, source=source, combat=True)
    eng.resolve_until_stable()
    assert source.counters.get('+1/+1', 0) == (counters + 1 if counters < 4 else counters)
    assert bool(eng.state.pending_choice) == searches
    if searches:
        assert eng.state.pending_choice['kind'] == 'search'


@pytest.mark.parametrize('counters', [0, 1])
def test_encumbered_reejerey_counter_gate_only_triggers_when_a_counter_exists(counters):
    eng = game()
    source = board(eng, DB.get_card('Encumbered Reejerey'))
    if counters:
        source.counters['-1/-1'] = counters
    eng.rules.set_tapped(source, True)
    assert bool(eng.rules.pending_triggers) == bool(counters)
    eng.resolve_until_stable()
    assert source.counters.get('-1/-1', 0) == 0
