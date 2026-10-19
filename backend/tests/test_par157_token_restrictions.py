"""Token-owned abilities use native parsing and shared combat restrictions."""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _hand, _creature
from test_par157_back_selections import _cached


def _settle(eng):
    eng.resolve_until_stable()
    while eng.state.pending_choice:
        assert eng.state.pending_choice['kind'] == 'scry'
        eng.resolve_pending_choice(eng.state.pending_choice['options'][0]['id'])
        eng.resolve_until_stable()


@pytest.mark.parametrize('tail', ['non-spirit creatures', 'creatures with power 2 or greater'])
def test_compound_restriction_retains_both_directions(tail):
    specs = static_effect_specs(f"~ can't block or be blocked by {tail}")
    assert [s.params['kind'] for s in specs] == ['cant_block_filtered', 'cant_be_blocked_by']
    assert specs[0].params['filter'] == specs[1].params['filter']


@pytest.mark.parametrize('ability', ["~ can't block or be blocked by non-imaginary creatures",
                                      '~ draws 3 cards whenever convenient'])
def test_unknown_token_abilities_fail_closed(ability):
    assert not parse_effect_body(f'create a 1/1 colorless spirit creature token with "{ability}"')


@pytest.mark.full_cache
def test_kuruk_reaches_back_and_cast_trigger_makes_a_native_restricted_spirit():
    eng = _engine()
    card = _cached('The Legend of Kuruk // Avatar Kuruk')
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    _settle(eng)
    for _ in range(2):
        eng.rules.advance_sagas(eng.state.player_by_id('p1'))
        _settle(eng)
    assert source.transformed and source.name == card.back_name
    spell = _hand(eng, Card(id='spell', name='Spell', type_line='Instant',
                           is_instant=True, oracle_text='You gain 1 life.'))
    eng.cast_spell(eng.state.player_by_id('p1'), spell)
    _settle(eng)
    token = next(obj for obj in eng.state.battlefield if obj.is_token)
    spirit = _bf(eng, Card(id='spirit', name='Spirit', type_line='Creature — Spirit',
                           is_creature=True, power=2, toughness=2), 'p2')
    bear = _bf(eng, _creature('Bear'), 'p2')
    eng.recompute_continuous_effects()
    token.attacking = True
    token.combat_defender = {'kind': 'player', 'id': 'p2'}
    assert eng.can_block(eng.state.player_by_id('p2'), spirit, token)
    assert not eng.can_block(eng.state.player_by_id('p2'), bear, token)
    token.attacking = False
    spirit.attacking = bear.attacking = True
    spirit.combat_defender = bear.combat_defender = {'kind': 'player', 'id': 'p1'}
    assert eng.can_block(eng.state.player_by_id('p1'), token, spirit)
    assert not eng.can_block(eng.state.player_by_id('p1'), token, bear)


@pytest.mark.full_cache
def test_comma_terminated_token_trigger_keeps_tend_the_pests_modeled():
    assert parse_oracle(_cached('Tend the Pests')).modeled


def test_token_owned_scaling_static_counts_its_own_controller_artifacts():
    eng = _engine()
    source = _bf(eng, Card(id='source', name='Source', type_line='Artifact'))
    _bf(eng, Card(id='other', name='Other', type_line='Artifact'), 'p2')
    specs = parse_effect_body('create a 0/0 colorless construct artifact creature token with '
                              '"~ gets +1/+1 for each artifact you control."')
    assert specs
    build_effects(specs, source)[0].apply(eng.rules.context)
    eng.resolve_until_stable()
    token = next(obj for obj in eng.state.battlefield if obj.is_token)
    assert token.power == token.toughness == 2
    token.controller_id = 'p2'
    eng.recompute_continuous_effects()
    assert token.power == token.toughness == 2
    _bf(eng, Card(id='third', name='Third', type_line='Artifact'), 'p2')
    eng.recompute_continuous_effects()
    assert token.power == token.toughness == 3
