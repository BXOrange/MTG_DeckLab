"""Keeper categories form a union; all players choose before sacrifice."""
import pytest
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _hand, _creature
from test_par157_back_selections import _cached

TEXT = ('each opponent chooses an artifact, a creature, an enchantment, and a planeswalker '
        'from among the nonland permanents they control, then sacrifices the rest')


def _put(eng, name, types, player='p2', **kwargs):
    return _bf(eng, Card(id=name, name=name, type_line=types, **kwargs), player)


def _mix(eng):
    a = _put(eng, 'A', 'Artifact Creature — Golem', is_creature=True, power=2, toughness=2)
    b = _put(eng, 'B', 'Artifact Creature — Golem', is_creature=True, power=2, toughness=2)
    enchantments = [_put(eng, f'E{i}', 'Enchantment') for i in range(2)]
    walkers = [_put(eng, f'W{i}', 'Planeswalker — Example', loyalty=3) for i in range(2)]
    land = _put(eng, 'Land Artifact', 'Artifact Land', is_land=True)
    battle = _put(eng, 'Battle', 'Battle — Siege', defense=4)
    return a, b, enchantments, walkers, land, battle


def _choose(eng, obj):
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'choose_objects'
    assert str(obj.instance_id) in {o['id'] for o in eng.state.pending_choice['options']}
    eng.resolve_pending_choice(str(obj.instance_id))


def _apply(eng, source, text=TEXT):
    specs = parse_effect_body(text)
    assert specs
    for effect in build_effects(specs, source):
        assert not effect.target_specs
        effect.apply(eng.rules.context)


@pytest.mark.parametrize('same', [True, False])
def test_multitype_keepers_may_fill_multiple_slots_or_form_a_union(same):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    a, b, enchantments, walkers, land, battle = _mix(eng)
    objects = [a, b, *enchantments, *walkers, land, battle]
    _apply(eng, source)
    assert eng.state.pending_choice['player_id'] == 'p2'
    assert str(land.instance_id) not in {o['id'] for o in eng.state.pending_choice['options']}
    _choose(eng, a)
    _choose(eng, a if same else b)
    _choose(eng, enchantments[0])
    assert all(o.zone == Zone.BATTLEFIELD for o in objects)
    _choose(eng, walkers[0])
    eng.resolve_until_stable()
    assert a.zone == enchantments[0].zone == walkers[0].zone == land.zone == Zone.BATTLEFIELD
    assert b.zone == (Zone.GRAVEYARD if same else Zone.BATTLEFIELD)
    assert enchantments[1].zone == walkers[1].zone == battle.zone == Zone.GRAVEYARD
    assert source.zone == Zone.BATTLEFIELD


def test_clone_retains_partial_keeper_choices_without_mutating_the_original():
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    a, b, enchantments, walkers, land, battle = _mix(eng)
    _apply(eng, source)
    _choose(eng, a)
    clone = GameEngine(eng.state.clone())
    _choose(clone, clone.state.find_object(a.instance_id))
    _choose(clone, clone.state.find_object(enchantments[0].instance_id))
    _choose(clone, clone.state.find_object(walkers[0].instance_id))
    assert clone.state.find_object(b.instance_id).zone == Zone.GRAVEYARD
    assert all(o.zone == Zone.BATTLEFIELD for o in [a, b, *enchantments, *walkers, battle])
    _choose(eng, b)
    _choose(eng, enchantments[1])
    _choose(eng, walkers[1])
    assert a.zone == b.zone == enchantments[1].zone == walkers[1].zone == Zone.BATTLEFIELD


def test_every_player_finishes_choosing_in_apnap_order_before_any_sacrifice():
    eng = GameEngine.new_game([('p1', 'One', []), ('p2', 'Two', []), ('p3', 'Three', [])], starting_hand=0)
    eng.state.active_player_index = 1
    source = _bf(eng, _creature('Source'))
    artifacts = {pid: [_put(eng, f'{pid}-{i}', 'Artifact', pid) for i in range(2)] for pid in ['p1', 'p2', 'p3']}
    _apply(eng, source, 'each player chooses an artifact from among the artifacts they control, then sacrifices the rest')
    for pid in ['p2', 'p3', 'p1']:
        assert eng.state.pending_choice['player_id'] == pid
        assert all(obj.zone == Zone.BATTLEFIELD for pair in artifacts.values() for obj in pair)
        _choose(eng, artifacts[pid][0])
    assert all(pair[0].zone == Zone.BATTLEFIELD and pair[1].zone == Zone.GRAVEYARD for pair in artifacts.values())
    batches = [event for event in eng.state.event_log if event.type == EventType.EVENT_BATCH and event.get('batch_of') == EventType.SACRIFICE]
    assert len(batches[-1].get('members')) == 3


def test_missing_categories_are_skipped_and_unsacrificable_objects_can_be_kept():
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    kept = _put(eng, 'Only keeper', 'Artifact Creature', is_creature=True, power=2, toughness=2)
    kept.cant_be_sacrificed_this_turn = True
    battle = _put(eng, 'Unkeepable', 'Battle — Siege', defense=4)
    _apply(eng, source)
    assert not eng.state.pending_choice
    assert kept.zone == Zone.BATTLEFIELD and battle.zone == Zone.GRAVEYARD


def test_a_kept_visit_does_not_migrate_to_a_later_visit_during_a_pending_selection():
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    a, b, enchantments, walkers, land, battle = _mix(eng)
    _apply(eng, source)
    _choose(eng, a)
    eng.rules.blink(a)
    _choose(eng, b)
    _choose(eng, enchantments[0])
    _choose(eng, walkers[0])
    # Neither the retained visit nor the original affected pool names the new A.
    assert a.zone == b.zone == Zone.BATTLEFIELD
    assert battle.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('text', [
    TEXT.replace('an artifact, a creature', 'an artifact, a dragon'),
    TEXT.replace('an artifact, a creature', 'an artifact, an artifact'),
    TEXT + ' and draw 3 cards instead of sacrificing',
])
def test_unknown_categories_duplicates_and_unknown_actions_fail_closed(text):
    assert not parse_effect_body(text)


@pytest.mark.full_cache
def test_ajani_casts_front_transforms_from_cat_death_and_executes_minus_four():
    eng = _engine()
    player = eng.state.player_by_id('p1')
    card = _cached('Ajani, Nacatl Pariah // Ajani, Nacatl Avenger')
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _hand(eng, card)
    player.mana_pool.add_many({'C': 1, 'W': 1})
    eng.cast_spell(player, source)
    eng.resolve_until_stable()
    cat = next(obj for obj in eng.state.battlefield if obj.is_token)
    eng.rules.put_into_graveyard(cat)
    eng.resolve_until_stable()
    eng.resolve_pending_choice('do')
    assert source.transformed and source.name == card.back_name and source.counters['loyalty'] == 3
    a, b, enchantments, walkers, land, battle = _mix(eng)
    source.counters['loyalty'] = 4
    eng.activate_ability(player, source, 2)
    eng.resolve_until_stable()
    _choose(eng, a)
    _choose(eng, a)
    _choose(eng, enchantments[0])
    _choose(eng, walkers[0])
    assert a.zone == enchantments[0].zone == walkers[0].zone == land.zone == Zone.BATTLEFIELD
    assert b.zone == enchantments[1].zone == walkers[1].zone == battle.zone == Zone.GRAVEYARD


@pytest.mark.full_cache
def test_liliana_reuses_keeper_union_instead_of_independent_type_cuts():
    eng = _engine()
    source = _bf(eng, _cached('Liliana, Dreadhorde General'))
    a = _put(eng, 'A', 'Artifact Creature', is_creature=True, power=2, toughness=2)
    b = _put(eng, 'B', 'Artifact Creature', is_creature=True, power=2, toughness=2)
    extra = _put(eng, 'Extra', 'Artifact')
    land = _put(eng, 'Kept Land', 'Land', is_land=True)
    source.counters['loyalty'] = 9
    eng.activate_ability(eng.state.player_by_id('p1'), source, 2)
    eng.resolve_until_stable()
    _choose(eng, b)  # creature slot first; neither object is sacrificed yet
    assert a.zone == b.zone == extra.zone == Zone.BATTLEFIELD
    _choose(eng, a)  # artifact slot can select the other multitype permanent
    assert a.zone == b.zone == land.zone == Zone.BATTLEFIELD
    assert extra.zone == Zone.GRAVEYARD


@pytest.mark.full_cache
@pytest.mark.parametrize('borrowed', [False, True])
def test_a_sacrificed_blood_artist_sees_the_other_simultaneous_sacrifices(borrowed):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    kept = _put(eng, 'Kept', 'Artifact Creature', is_creature=True, power=2, toughness=2)
    artist = _bf(eng, _cached('Blood Artist'), 'p1' if borrowed else 'p2')
    artist.controller_id = 'p2'
    other = _put(eng, 'Other victim', 'Artifact Creature', is_creature=True, power=2, toughness=2)
    _apply(eng, source)
    _choose(eng, kept)
    _choose(eng, kept)
    while eng.state.pending_choice:
        assert eng.state.pending_choice['kind'] == 'trigger_target'
        eng.resolve_pending_choice('p1')
    eng.resolve_until_stable()
    assert artist.zone == other.zone == Zone.GRAVEYARD
    assert eng.state.player_by_id('p1').life == 18
    assert eng.state.player_by_id('p2').life == 22
