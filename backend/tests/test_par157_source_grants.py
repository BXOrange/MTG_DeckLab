"""Source-granted abilities compose quoted grammar, duration and search filters."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import PERMANENT_CARD_TYPES
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached


def _apply(eng, source, text):
    specs = parse_effect_body(text)
    assert specs
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context)
    eng.recompute_continuous_effects()


@pytest.mark.full_cache
def test_huatli_front_transforms_and_back_chapters_grant_search_and_finish():
    eng = _engine()
    card = _cached('Huatli, Poet of Unity // Roar of the Fifth People')
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    eng.resolve_until_stable()
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'C': 3, 'R': 2})
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert source.transformed and source.name == card.back_name
    dinosaurs = [o for o in eng.state.battlefield if o.is_token and 'Dinosaur' in o.card.type_line]
    assert len(dinosaurs) == 2
    for obj in dinosaurs:
        obj.summoning_sick = False
    eng.rules.advance_sagas(player)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert dinosaurs[0].granted_mana_options == [{'R': 1}, {'G': 1}, {'W': 1}]
    for i, color in enumerate(['R', 'G', 'W']):
        dinosaurs[0].tapped = False
        before = player.mana_pool.total()
        result = eng.tap_for_mana(player, dinosaurs[0], ability_index=i)
        assert result == {color: 1} and player.mana_pool.total() == before + 1
    dinosaur = GameObject(Card(id='search dino', name='Search Dinosaur', type_line='Creature — Dinosaur',
        is_creature=True, power=4, toughness=4), owner_id='p1', zone=Zone.LIBRARY)
    player.library.append(dinosaur)
    eng.rules.advance_sagas(player)
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'search'
    options = eng.state.pending_choice['options']
    assert any(str(o['id']) == str(dinosaur.instance_id) for o in options)
    assert all(o.get('instance_id') in (None, dinosaur.instance_id) for o in options)
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(dinosaur.instance_id))
    assert clone.state.find_object(dinosaur.instance_id).zone == Zone.HAND
    assert dinosaur.zone == Zone.LIBRARY
    eng.resolve_pending_choice(str(dinosaur.instance_id))
    eng.rules.advance_sagas(player)
    eng.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD
    assert all('double_strike' in obj.granted_keywords and 'trample' in obj.granted_keywords for obj in dinosaurs)
    assert all(not obj.granted_mana_options for obj in dinosaurs)


@pytest.mark.parametrize('duration', ['', ' until end of turn', ' until your next turn'])
def test_static_grant_is_dynamic_for_creatures_but_bound_to_one_source_visit(duration):
    eng = _engine()
    source = _bf(eng, Card(id='grantor', name='Grantor', type_line='Enchantment'))
    _apply(eng, source, '~ gains "creatures you control have flying."' + duration)
    creature = _bf(eng, _creature('Later creature'))
    eng.recompute_continuous_effects()
    assert 'flying' in creature.granted_keywords
    eng.rules.exile(source)
    eng.rules.return_from_exile(source, source.zone_incarnation)
    eng.recompute_continuous_effects()
    assert 'flying' not in creature.granted_keywords


@pytest.mark.parametrize('mana,expected', [
    ('{r}{g}', [{'R': 1, 'G': 1}]),
    ('{u} or {b}', [{'U': 1}, {'B': 1}]),
    ('{r}, {g}, or {w}', [{'R': 1}, {'G': 1}, {'W': 1}]),
    ('{u}{u}, {b}{b}, {r}{r}, or {g}{g}', [{'U': 2}, {'B': 2}, {'R': 2}, {'G': 2}]),
])
def test_granted_mana_has_independent_options_and_amounts(mana, expected):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    _apply(eng, source, f'~ gains "{{t}}: add {mana}."')
    assert source.granted_mana_options == expected


@pytest.mark.parametrize('words,criteria', [
    ('dinosaur', {'type': 'dinosaur'}),
    ('rebel permanent', {'type': 'rebel', 'or': [{'type': list(PERMANENT_CARD_TYPES)}]}),
    ('dinosaur creature', {'all_types': ['dinosaur'], 'type': 'creature'}),
    ('time lord', {'type': 'time lord'}),
])
def test_search_reuses_subtype_and_card_type_axes(words, criteria):
    specs = parse_effect_body(f'search your library for a {words} card, reveal it, put it into your hand, then shuffle')
    assert specs and specs[0].params['criteria'] == criteria


@pytest.mark.parametrize('text', [
    'this saga gains "creatures you control have an imaginary ability."',
    '~ gains "{t}: add {r}, {g}."',
    '~ gains "{t}: add {z} or {r}."',
    'search your library for an imaginary card, reveal it, put it into your hand, then shuffle',
])
def test_unknown_ability_mana_and_search_qualifiers_fail_closed(text):
    assert parse_effect_body(text) is None


def test_granted_static_follows_current_controller_and_clone_without_surviving_duration():
    eng = _engine()
    source = _bf(eng, Card(id='grantor', name='Grantor', type_line='Enchantment'))
    own = _bf(eng, _creature('Own creature'))
    other = _bf(eng, _creature('Other creature'), 'p2')
    _apply(eng, source, '~ gains "creatures you control have flying." until end of turn')
    assert 'flying' in own.granted_keywords and 'flying' not in other.granted_keywords
    clone = GameEngine(eng.state.clone())
    clone.state.find_object(source.instance_id).controller_id = 'p2'
    clone.recompute_continuous_effects()
    assert 'flying' not in clone.state.find_object(own.instance_id).granted_keywords
    assert 'flying' in clone.state.find_object(other.instance_id).granted_keywords
    assert 'flying' in own.granted_keywords and 'flying' not in other.granted_keywords
    clone._step_cleanup()
    assert 'flying' not in clone.state.find_object(other.instance_id).granted_keywords


@pytest.mark.parametrize('body', ['draw a card', 'target creature gets +1/+1 until end of turn'])
def test_quoted_one_shot_effect_is_not_misread_as_a_granted_ability(body):
    assert parse_effect_body(f'~ gains "{body}."') is None


@pytest.mark.parametrize('subtype', ['soldier', 'rebel', 'lesson'])
def test_explicit_permanent_subtype_search_does_not_find_nonpermanent_cards(subtype):
    from mtg_analyzer.models.cards import card_query
    specs = parse_effect_body(f'search your library for a {subtype} permanent card, reveal it, '
                              'put it into your hand, then shuffle')
    criteria = specs[0].params['criteria']
    permanent = Card(id='permanent', name='Permanent', type_line=f'Kindred Enchantment — {subtype.title()}')
    spell = Card(id='spell', name='Spell', type_line=f'Kindred Sorcery — {subtype.title()}')
    assert card_query.matches(permanent, criteria)
    assert not card_query.matches(spell, criteria)


@pytest.mark.parametrize('oracle,keywords', [
    ('Changeling (This card is every creature type.)', ['Changeling']),
    ('Changeling', []),
    ('All Types is every creature type (even if this card is not on the battlefield).', []),
])
def test_card_search_subtypes_include_changeling_and_unconditional_type_cdas(oracle, keywords):
    from mtg_analyzer.models.cards import card_query
    card = Card(id='all types', name='All Types', type_line='Artifact Creature — Shapeshifter',
        is_creature=True, power=2, toughness=2, keywords=keywords, oracle_text=oracle)
    assert card_query.matches(card, {'type': 'dinosaur'})
    assert card_query.matches(card, {'all_types': ['dinosaur', 'time lord']})
    assert not card_query.matches(card, {'type': 'gate'})
    assert not card_query.matches(card, {'type': 'forest'})


@pytest.mark.parametrize('oracle', [
    'As long as you control a Forest, All Types is every creature type.',
    'Target creature is every creature type until end of turn.',
    'Creatures you control are every creature type.',
])
def test_card_search_does_not_treat_conditional_or_granted_types_as_printed_cdas(oracle):
    from mtg_analyzer.models.cards import card_query
    card = Card(id='conditional', name='All Types', type_line='Creature — Shapeshifter', oracle_text=oracle)
    assert not card_query.matches(card, {'type': 'dinosaur'})


@pytest.mark.full_cache
def test_huatli_dinosaur_search_offers_a_changeling_without_dinosaur_in_its_type_line():
    eng = _engine()
    card = _cached('Huatli, Poet of Unity // Roar of the Fifth People')
    source = _bf(eng, card)
    player = eng.state.player_by_id('p1')
    changeling = GameObject(_cached('Universal Automaton'), owner_id='p1', zone=Zone.LIBRARY)
    player.library.append(changeling)
    _apply(eng, source, 'search your library for a dinosaur card, reveal it, put it into your hand, then shuffle')
    assert eng.state.pending_choice
    assert str(changeling.instance_id) in {str(o['id']) for o in eng.state.pending_choice['options']}
    eng.resolve_pending_choice(str(changeling.instance_id))
    assert changeling.zone == Zone.HAND
