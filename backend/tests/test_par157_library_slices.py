"""Reachable backs reuse graveyard unions and deterministic library slices."""
import pytest
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached


@pytest.mark.parametrize('slice_text,kept', [
    ('the top 2 cards', [0, 1, 2]), ('the bottom 2 cards', [2, 3, 4]),
    ('all but the bottom 2 cards', [0, 1]), ('all but the top 2 cards', [3, 4]),
    ('all cards', []), ('all but the bottom card', [0]),
])
def test_library_slice_axes_keep_the_correct_cards_and_order(slice_text, kept):
    eng = _engine()
    source = _bf(eng, _creature('Slicer'))
    victim = eng.state.player_by_id('p2')
    original = list(victim.library)
    text = f"exile {slice_text} of target player's library"
    specs = parse_effect_body(text)
    assert specs
    effects = build_effects(specs, source)
    assert effects[0].target_spec.kind == 'player'
    effects[0].apply(eng.rules.context, [victim])
    assert victim.library == [original[i] for i in kept]
    assert all(obj.zone == (Zone.LIBRARY if i in kept else Zone.EXILE) for i, obj in enumerate(original))
    assert len(eng.state.player_by_id('p1').library) == 5


@pytest.mark.parametrize('owner,affected', [('your', ['p1']), ("each player's", ['p1', 'p2']),
                                           ("each opponent's", ['p2']), ("target opponent's", ['p2'])])
def test_library_owner_face_down_and_amount_axes_compose(owner, affected):
    eng = _engine()
    source = _bf(eng, _creature('Slicer'))
    effects = build_effects(parse_effect_body(f'exile the bottom card of {owner} library face down'), source)
    effects[0].apply(eng.rules.context, [eng.state.player_by_id('p2')])
    for player in eng.state.players:
        assert len(player.library) == (4 if player.id in affected else 5)
        assert all(obj.face_down_in_exile for obj in player.exile)


@pytest.mark.parametrize('size', [0, 1, 2])
def test_retained_bottom_card_is_safe_in_short_or_empty_libraries(size):
    eng = _engine(library=size)
    source = _bf(eng, _creature('Slicer'))
    specs = parse_effect_body('exile all but the bottom card of your library')
    build_effects(specs, source)[0].apply(eng.rules.context)
    assert len(eng.state.player_by_id('p1').library) == min(1, size)


@pytest.mark.parametrize('text', [
    "exile all but a random card of target player's library",
    "exile the top 2 cards of target player's library until end of turn",
    'exile the top 2 creature cards of your library',
])
def test_unknown_slice_or_rider_is_not_claimed(text):
    assert match_clause(text) is None


@pytest.mark.full_cache
@pytest.mark.parametrize('mode', ['creature', 'planeswalker', 'library'])
def test_nicol_bolas_reaches_back_and_uses_shared_graveyard_and_library_axes(mode):
    eng = _engine()
    player = eng.state.player_by_id('p1')
    opponent = eng.state.player_by_id('p2')
    card = _cached('Nicol Bolas, the Ravager // Nicol Bolas, the Arisen')
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    eng.resolve_until_stable()
    player.mana_pool.add_many({'C': 4, 'U': 1, 'B': 1, 'R': 1})
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert source.transformed and source.name == card.back_name
    assert source.counters['loyalty'] == 7
    if mode == 'library':
        source.counters['loyalty'] = 12
        original = list(opponent.library)
        eng.activate_ability(player, source, 3, targets=[opponent])
        clone = GameEngine(eng.state.clone())
        clone.resolve_until_stable()
        copied = clone.state.player_by_id('p2')
        assert [obj.instance_id for obj in copied.library] == [original[0].instance_id]
        assert len(copied.exile) == 4 and len(opponent.library) == 5
        return
    target_card = (_creature('Returned creature') if mode == 'creature' else Card(
        id='Returned walker', name='Returned walker', type_line='Planeswalker — Example',
        loyalty=3))
    target = _bf(eng, target_card, 'p2')
    artifact = _bf(eng, Card(id='Artifact', name='Artifact', type_line='Artifact'), 'p2')
    eng.rules.put_into_graveyard(target)
    eng.rules.put_into_graveyard(artifact)
    effect = source.activated_abilities[2].effects[0]
    offered = {row['instance_id'] for row in legal_targets(eng.state, 'p1', effect.target_spec, source)}
    assert target.instance_id in offered and artifact.instance_id not in offered
    eng.activate_ability(player, source, 2, targets=[target])
    eng.resolve_until_stable()
    assert target.zone == Zone.BATTLEFIELD and target.controller_id == 'p1' and target.owner_id == 'p2'
    if mode == 'planeswalker':
        assert target.counters['loyalty'] == 3
