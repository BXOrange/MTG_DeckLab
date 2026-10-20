"""Animation composes previous targets, retained types and lasting grants."""
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
import pytest
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _hand, _creature
from test_par157_back_selections import _cached

TEXT = "untap up to 6 target lands. they become 6/6 elemental creatures. they're still lands"


def _land(eng, name, who='p1'):
    return _bf(eng, Card(id=name, name=name, type_line='Land', is_land=True), who)


@pytest.mark.parametrize('pronoun', ['it', 'they', 'that land', 'those lands'])
def test_animation_referent_is_gated_and_reuses_the_shared_builder(pronoun):
    text = f'{pronoun} becomes a 3/4 blue elemental creature with flying until end of turn'
    assert match_clause(text) is None
    specs = match_clause(text, reading=ClauseReading(previous_subject=True))
    assert specs and specs[0].type == 'grant_until'
    assert specs[0].params['previous_subject'] and specs[0].params['target_kind'] is None
    assert specs[0].params['duration'] == 'end_of_turn'


def test_animation_applies_to_all_previous_targets_and_persists_without_reaching_later_visits():
    eng = _engine()
    source = _bf(eng, _creature('Animator'))
    lands = [_land(eng, f'Chosen {i}', 'p1' if i == 0 else 'p2') for i in range(2)]
    unchosen = _land(eng, 'Unchosen')
    for land in lands:
        land.tapped = True
    effects = build_effects(parse_effect_body(TEXT), source)
    effects[0].apply(eng.rules.context, lands)
    eng.rules.context.previous_targets = lands
    effects[1].apply(eng.rules.context)
    eng.rules.put_into_graveyard(source)
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert all(land.is_creature and land.is_land and land.power == land.toughness == 6 for land in lands)
    assert not unchosen.is_creature
    clone = GameEngine(eng.state.clone())
    copied = clone.state.find_object(lands[0].instance_id)
    clone.rules.blink(copied)
    clone.recompute_continuous_effects()
    assert copied.is_land and not copied.is_creature
    assert lands[0].is_creature


@pytest.mark.parametrize('text', [
    "they become 6/6 elemental creatures except on Tuesdays",
    "they become 6/6 invisible creatures",
    "they become 6/6 elemental creatures with unknownword",
])
def test_animation_does_not_drop_unknown_types_abilities_or_tails(text):
    assert match_clause(text, reading=ClauseReading(previous_subject=True)) is None


@pytest.mark.full_cache
@pytest.mark.parametrize('mode', ['token', 'lands', 'zero'])
def test_nissa_reaches_back_and_uses_shared_token_and_animation_axes(mode):
    eng = _engine()
    player = eng.state.player_by_id('p1')
    lands = [_land(eng, f'Own Land {i}') for i in range(6)]
    card = _cached('Nissa, Vastwood Seer // Nissa, Sage Animist')
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    eng.resolve_until_stable()
    seventh = _hand(eng, Card(id='Seventh', name='Seventh', type_line='Land', is_land=True))
    eng.play_land(player, seventh)
    eng.resolve_until_stable()
    assert source.transformed and source.name == card.back_name and source.counters['loyalty'] == 3
    if mode == 'token':
        eng.activate_ability(player, source, 1)
        eng.resolve_until_stable()
        tokens = [obj for obj in eng.state.battlefield if obj.is_token]
        assert len(tokens) == 1
        token = tokens[0]
        assert token.name == 'Ashaya, the Awoken World'
        assert token.is_legendary and token.power == token.toughness == 4
        assert token.colors == {'G'} and 'Elemental' in token.card.type_line
    else:
        other = _land(eng, 'Opponent Land', 'p2')
        chosen = [] if mode == 'zero' else [lands[0], lands[1], other]
        source.counters['loyalty'] = 7
        for land in [*lands, other]:
            land.tapped = True
        eng.activate_ability(player, source, 2, targets=chosen)
        clone = GameEngine(eng.state.clone())
        clone.resolve_until_stable()
        for obj in [*lands, other]:
            copied = clone.state.find_object(obj.instance_id)
            assert copied.is_creature == (obj in chosen)
            assert copied.tapped == (obj not in chosen)
            if obj in chosen:
                assert copied.is_land and copied.power == copied.toughness == 6
        assert not lands[0].is_creature


def test_named_legendary_tokens_preserve_printed_spelling_in_nested_effects():
    card = Card(id='Name Test', name='Name Test', is_sorcery=True, type_line='Sorcery',
        oracle_text='Choose one —\n• Create Alia, Keeper of the Gate, a legendary 2/3 white Human creature token.\n• Draw a card.')
    parsed = parse_oracle(card)
    assert parsed.modeled
    assert parsed.specs[0].modes['options'][0][0].params['token_name'] == 'Alia, Keeper of the Gate'
