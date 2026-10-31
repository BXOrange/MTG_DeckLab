"""PAR-219: shared name operands must restrict actual searches and casts."""
import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.combat import matches_object_filter
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import parse_object_phrase
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import game, card, filler, cast, answer
from tests.test_mec118_opponent_choice import _db_card


@pytest.mark.parametrize('name', [
    "Grasping Current", "Angrath's Fury", "Ashiok's Forerunner", "Sun-Blessed Mount",
    "Sanctum of All", "Tale of Momo",
    "Mask of the Mimic", "Bifurcate", "Pack Hunt",
    "Ixalan's Binding", "Exclusion Ritual", "Circu, Dimir Lobotomist",
])
def test_real_card_models(name):
    parsed = parse_oracle(_db_card(name))
    assert parsed.modeled, parsed.unclaimed


@pytest.mark.parametrize('text', [
    'search your library for a card with the same name as that creature, put it into your hand, then shuffle',
    'search your library for a card named jace, then draw a card, put it into your hand, then shuffle',
    'search your library for a card with the same name as target imaginary creature, put it into your hand, then shuffle',
    'search your library for a card with the same name as target creatures, put it into your hand, then shuffle',
])
def test_unknown_or_unbound_references_fail_closed(text):
    assert parse_effect_body(text) is None


def test_previous_reference_requires_a_reading():
    text = 'search your library for a creature card with the same name as that creature, put it onto the battlefield, then shuffle'
    assert parse_effect_body(text) is None
    assert parse_effect_body(text, reading=ClauseReading(previous_subject=True))


def test_source_name_filter_recombines_and_excludes_nameless():
    eng = game()
    source = filler(eng, 'Fire // Ice', type_line='Artifact')
    same = filler(eng, 'Ice', type_line='Legendary Artifact Creature', power=2, toughness=2)
    other = filler(eng, 'Other', type_line='Legendary Artifact Creature', power=2, toughness=2)
    filt, scope = parse_object_phrase('legendary artifact creatures with the same name as ~', plural=True)
    assert scope is None
    assert matches_object_filter(same, filt, reference=source, state=eng.state)
    assert not matches_object_filter(other, filt, reference=source, state=eng.state)


def test_named_comma_search_finds_graveyard_card():
    eng = game()
    good = card(eng, 'Jace, Ingenious Mind-Mage', zone=Zone.GRAVEYARD)
    filler(eng, 'Jace', zone=Zone.GRAVEYARD)
    spell = card(eng, 'Grasping Current', zone=Zone.HAND)
    cast(eng, spell, targets=[])
    assert eng.state.pending_choice is not None
    assert {entry['name'] for entry in eng.state.pending_choice['eligible']} == {good.name}
    eng.rules.resolve_choice(good.instance_id)
    assert good in eng.state.player_by_id('p1').hand


@pytest.mark.parametrize('name', ['Bifurcate', 'Pack Hunt'])
def test_target_name_search_only_offers_same_name(name):
    eng = game()
    target = filler(eng, 'Shared', power=2, toughness=2)
    good = filler(eng, 'Shared', zone=Zone.LIBRARY)
    filler(eng, 'Different', zone=Zone.LIBRARY)
    spell = card(eng, name, zone=Zone.HAND)
    cast(eng, spell, targets=[target])
    choice = eng.state.pending_choice
    assert choice and {entry['name'] for entry in choice['eligible']} == {'Shared'}
    eng.rules.resolve_choice(good.instance_id)
    assert good.zone == (Zone.BATTLEFIELD if name == 'Bifurcate' else Zone.HAND)


def test_linked_exile_cast_prohibition_ends_when_exile_visit_ends():
    eng = game()
    victim = filler(eng, 'Shared', power=2, toughness=2, player='p2')
    source = card(eng, "Ixalan's Binding", zone=Zone.HAND)
    cast(eng, source, targets=[victim])
    answer(eng, lambda choice: str(victim.instance_id))
    eng.resolve_until_stable()
    assert victim.zone == Zone.EXILE
    player = eng.state.player_by_id('p2')
    same = filler(eng, 'Shared', player='p2', zone=Zone.HAND)
    other = filler(eng, 'Other', player='p2', zone=Zone.HAND)
    assert continuous.cast_prohibited(eng.state, player, same.card, 'hand')
    assert not continuous.cast_prohibited(eng.state, player, other.card, 'hand')
    assert not continuous.cast_prohibited(eng.state, eng.state.player_by_id('p1'), same.card, 'hand')
    eng.rules.put_into_graveyard(victim)
    assert not continuous.cast_prohibited(eng.state, player, same.card, 'hand')


@pytest.mark.parametrize('name', ['Exclusion Ritual', 'Circu, Dimir Lobotomist'])
def test_name_reader_stamps_actual_exile_producers(name):
    parsed = parse_oracle(_db_card(name))
    producers = [effect for spec in parsed.specs for effect in spec.effects
                 if effect.type in {'exile', 'exile_top_of_library'}]
    assert producers and all(effect.params.get('track_exiled_with') for effect in producers)


def test_exclusion_ritual_prohibits_both_players_and_drops_a_reexiled_visit():
    eng = game()
    victim = filler(eng, 'Shared', power=2, toughness=2, player='p2')
    ritual = card(eng, 'Exclusion Ritual', zone=Zone.HAND)
    cast(eng, ritual)
    answer(eng, lambda _: str(victim.instance_id))
    eng.resolve_until_stable()
    for player in eng.state.players:
        assert continuous.cast_prohibited(eng.state, player, victim.card, 'hand')
    eng.rules.put_into_graveyard(victim)
    eng.rules.exile(victim)
    assert not continuous.cast_prohibited(eng.state, eng.state.players[0], victim.card, 'hand')


def test_shared_name_damage_group_does_not_target_other_members():
    eng = game()
    first = filler(eng, 'Shared', power=2, toughness=8)
    second = filler(eng, 'Shared', power=2, toughness=8, keywords=['Hexproof'])
    other = filler(eng, 'Different', power=2, toughness=8)
    cast(eng, card(eng, 'Homing Lightning', zone=Zone.HAND), targets=[first])
    assert first.damage_marked == second.damage_marked == 4
    assert other.damage_marked == 0


def test_combined_named_search_preserves_type_color_and_mana_value():
    specs = parse_effect_body('search your library and/or graveyard for a red creature card named shared with mana value 3 or less, reveal it, and put it into your hand. if you search your library this way, shuffle')
    assert specs[0].params['criteria'] == {'name': 'shared', 'type': 'creature', 'color': 'R', 'max_mana_value': 3}


def test_circu_library_exile_blocks_the_matching_name_in_both_live_and_cloned_games():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = game()
    card(eng, 'Circu, Dimir Lobotomist')
    victim = filler(eng, 'Shared', player='p2', zone=Zone.LIBRARY)
    cast(eng, card(eng, 'Opt', zone=Zone.HAND))
    answer(eng, lambda choice: 'p2' if choice['kind'] == 'trigger_target' else None)
    eng.resolve_until_stable()
    assert victim.zone == Zone.EXILE
    for current in (eng, GameEngine(eng.state.clone())):
        assert continuous.cast_prohibited(current.state, current.state.player_by_id('p2'), victim.card, 'hand')
        assert not continuous.cast_prohibited(current.state, current.state.player_by_id('p1'), victim.card, 'hand')


def test_pending_same_name_search_clone_keeps_the_captured_name():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = game()
    target = filler(eng, 'Shared', power=2, toughness=2)
    good = filler(eng, 'Shared', zone=Zone.LIBRARY)
    cast(eng, card(eng, 'Pack Hunt', zone=Zone.HAND), targets=[target])
    clone = GameEngine(eng.state.clone())
    for current in (eng, clone):
        assert {entry['name'] for entry in current.state.pending_choice['eligible']} == {'Shared'}
        current.rules.resolve_choice(good.instance_id)
        assert current.state.find_object(good.instance_id).zone == Zone.HAND


def test_search_name_constraint_intersects_existing_union():
    from mtg_analyzer.game.name_reference import resolve_search_names
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.models.cards.card_query import matches
    eng = game()
    source = filler(eng, 'Shared')
    context = GameContext(eng.state, eng.rules)
    criteria = resolve_search_names({'or': [{'type': 'instant'}, {'type': 'sorcery'}],
                                    'name_reference': {'kind': 'source'}}, context, source)
    creature = filler(eng, 'Shared', type_line='Creature')
    instant = filler(eng, 'Shared', type_line='Instant')
    assert matches(instant.card, criteria)
    assert not matches(creature.card, criteria)


def test_frostpyre_search_matches_own_graveyard_and_keeps_spell_type():
    eng = game()
    card(eng, 'Lightning Bolt', zone=Zone.GRAVEYARD)
    good = card(eng, 'Lightning Bolt', zone=Zone.LIBRARY)
    filler(eng, 'Lightning Bolt', zone=Zone.LIBRARY, type_line='Creature')
    card(eng, 'Opt', zone=Zone.GRAVEYARD, player='p2')
    card(eng, 'Opt', zone=Zone.LIBRARY)
    cast(eng, card(eng, 'Frostpyre Arcanist', zone=Zone.HAND))
    choice = eng.state.pending_choice
    assert choice and [entry['instance_id'] for entry in choice['eligible']] == [good.instance_id]
    eng.rules.resolve_choice(good.instance_id)
    assert good.zone == Zone.HAND


def test_dragonlord_uses_casting_players_graveyard():
    eng = game()
    card(eng, 'Dragonlord Kolaghan')
    card(eng, 'Grizzly Bears', zone=Zone.GRAVEYARD, player='p2')
    eng.state.active_player_index = 1
    cast(eng, card(eng, 'Grizzly Bears', zone=Zone.HAND, player='p2'))
    assert eng.state.player_by_id('p2').life == 10


def test_named_search_union_finds_either_the_name_or_the_independent_type():
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
    eng = game()
    source = card(eng, 'Forging the Tyrite Sword')
    halvar = card(eng, 'Halvar, God of Battle // Sword of the Realms', zone=Zone.LIBRARY)
    equipment = card(eng, 'Bonesplitter', zone=Zone.LIBRARY)
    filler(eng, 'an equipment card', type_line='Creature', zone=Zone.LIBRARY)
    parsed = parse_oracle(source.card)
    spec = parsed.specs[-1].effects[0]
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    effect.apply(GameContext(eng.state, eng.rules))
    assert {entry['instance_id'] for entry in eng.state.pending_choice['eligible']} == {halvar.instance_id, equipment.instance_id}
    eng.rules.resolve_choice(equipment.instance_id)
    assert equipment.zone == Zone.HAND


def test_unknown_search_union_member_fails_closed():
    assert parse_effect_body('search your library for a card named known or an imaginary card, put it into your hand, then shuffle') is None


def test_named_search_uses_both_split_names_but_only_the_front_of_a_dfc():
    from mtg_analyzer.models.cards.card_query import matches
    halvar = _db_card('Halvar, God of Battle // Sword of the Realms')
    split = _db_card('Fire // Ice')
    for key in ('name', 'same_name_as'):
        assert matches(halvar, {key: 'Halvar, God of Battle'})
        assert not matches(halvar, {key: 'Sword of the Realms'})
        assert matches(split, {key: 'Fire'})
        assert matches(split, {key: 'Ice'})
