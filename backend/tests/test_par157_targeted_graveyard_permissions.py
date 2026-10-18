"""Targeted graveyard grants compose exact visits and spell replacements."""
import pytest
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _hand, _creature
from test_par157_back_selections import _cached

TEXT = ('you may cast target instant or sorcery card from your graveyard this turn. '
        'if that spell would be put into your graveyard, exile it instead')


def _setup(text=TEXT):
    eng = _engine()
    player = eng.state.player_by_id('p1')
    source = _bf(eng, _creature('Grantor'))
    spell = _hand(eng, Card(id='Insight', name='Insight', type_line='Instant', is_instant=True,
        mana_cost_string='{1}', converted_mana_cost=1, oracle_text='Draw a card.'))
    player.hand.remove(spell)
    eng.rules.put_into_graveyard(spell)
    specs = parse_effect_body(text)
    assert specs
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context, [spell])
    return eng, player, source, spell


@pytest.mark.parametrize('exile', [False, True])
def test_normal_cost_permission_survives_source_and_clones(exile):
    eng, player, source, spell = _setup(TEXT if exile else TEXT.split('. ')[0])
    eng.rules.put_into_graveyard(source)
    assert not eng.can_cast(player, spell)
    player.mana_pool.add('C', 1)
    assert eng.can_cast(player, spell)
    clone = GameEngine(eng.state.clone())
    copied = clone.state.find_object(spell.instance_id)
    clone.cast_spell(clone.state.player_by_id('p1'), copied)
    clone.resolve_until_stable()
    assert copied.zone == (Zone.EXILE if exile else Zone.GRAVEYARD)
    assert spell.zone == Zone.GRAVEYARD
    assert not clone.state.temp_graveyard_cast_permissions


def test_replacement_follows_spell_across_turns_but_not_bounce_and_recast():
    eng, player, _, spell = _setup()
    player.mana_pool.add('C', 2)
    eng.cast_spell(player, spell)
    assert spell.cast_graveyard_exile_replacement
    clone = GameEngine(eng.state.clone())
    clone.state.internal_turn.number += 1
    clone.resolve_until_stable()
    assert clone.state.find_object(spell.instance_id).zone == Zone.EXILE
    assert eng.rules.return_spell_to_hand(eng.state.stack[-1])
    assert spell.zone == Zone.HAND and not spell.cast_graveyard_exile_replacement
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.GRAVEYARD


def test_permission_expires_and_does_not_follow_a_new_graveyard_visit():
    eng, player, _, spell = _setup()
    player.mana_pool.add('C', 2)
    eng.rules.return_to_hand(spell)
    player.hand.remove(spell)
    eng.rules.put_into_graveyard(spell)
    assert not eng.can_cast(player, spell)
    eng, player, _, spell = _setup()
    player.mana_pool.add('C', 1)
    eng._step_cleanup()
    assert not eng.state.temp_graveyard_cast_permission_visits
    assert not eng.can_cast(player, spell)


@pytest.mark.parametrize('text', [
    'you may cast target creature card from your graveyard this turn if the moon is purple',
    TEXT + ' except on Tuesdays',
    'you may cast target instant or sorcery card from your graveyard next turn',
])
def test_unknown_restrictions_are_not_silently_discarded(text):
    assert not parse_effect_body(text)


@pytest.mark.full_cache
def test_jace_front_reaches_back_and_minus_three_grants_exact_spell_permission():
    eng = _engine()
    player = eng.state.player_by_id('p1')
    card = _cached("Jace, Vryn's Prodigy // Jace, Telepath Unbound")
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    spell = _hand(eng, Card(id='Insight', name='Insight', type_line='Instant', is_instant=True,
        mana_cost_string='{1}', converted_mana_cost=1, oracle_text='Draw a card.'))
    player.hand.remove(spell)
    eng.rules.put_into_graveyard(spell)
    for i in range(4):
        player.graveyard.append(GameObject(_creature(f'Filler {i}'), owner_id='p1', zone=Zone.GRAVEYARD))
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.resolve_pending_choice(str(eng.state.pending_choice['options'][0]['id']))
    eng.resolve_until_stable()
    assert source.transformed and source.name == card.back_name
    assert source.counters['loyalty'] == 5
    eng.activate_ability(player, source, 1, targets=[spell])
    eng.resolve_until_stable()
    assert source.counters['loyalty'] == 2
    player.mana_pool.add('C', 1)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE


def test_an_additional_plain_grant_preserves_the_spell_replacement():
    eng, player, source, spell = _setup()
    for effect in build_effects(parse_effect_body(TEXT.split('. ')[0]), source):
        effect.apply(eng.rules.context, [spell])
    player.mana_pool.add('C', 1)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE


def test_a_grant_can_authorize_a_card_in_an_opponents_graveyard():
    eng, player, source, spell = _setup(TEXT.split(". ")[0])
    player.graveyard.remove(spell)
    spell.owner_id = spell.controller_id = 'p2'
    eng.state.player_by_id('p2').graveyard.append(spell)
    text = 'you may cast target instant or sorcery card from a graveyard this turn'
    for effect in build_effects(parse_effect_body(text), source):
        effect.apply(eng.rules.context, [spell])
    player.mana_pool.add('C', 1)
    assert eng.can_cast(player, spell)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.GRAVEYARD
    assert spell in eng.state.player_by_id("p2").graveyard


@pytest.mark.full_cache
@pytest.mark.parametrize('name', ['Heiko Yamazaki, the General', 'Norika Yamazaki, the Poet'])
def test_real_cards_reuse_the_targeted_permission_grammar(name):
    assert parse_oracle(_cached(name)).modeled
