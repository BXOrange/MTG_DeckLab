"""Maddening Hex uses actual casts, seeded dice and exact Aura visits."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game, RICH
from tests.support.star_trek import advance_to


def _board(players=4):
    engine = game(players=players, library=20)
    advance_to(engine, 'main1')
    source = card(engine, 'Maddening Hex', player='p2')
    source.attached_to = 'p1'
    return engine, source


def _cast(engine, kind='Instant', resolve=True):
    obj = filler(engine, 'Test spell', type_line=kind, zone=Zone.HAND,
                 power=2 if 'Creature' in kind else None, toughness=2 if 'Creature' in kind else None)
    engine.state.players[0].mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.players[0], obj)
    engine.rules.put_triggers_on_stack()
    if resolve:
        engine.resolve_until_stable()
    return obj


def test_specs_fresh_and_bound():
    engine, source = _board()
    a,b = specs_for(source.card), specs_for(source.card)
    assert len(a)==2 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1


@pytest.mark.parametrize('kind',['Instant','Sorcery','Artifact','Enchantment','Planeswalker'])
def test_noncreature_cast_rolls_deals_damage_and_moves(kind, monkeypatch):
    engine, source = _board()
    calls = []
    def random_int(n):
        calls.append(n)
        return n-1
    monkeypatch.setattr(engine.rules, 'random_int', random_int)
    _cast(engine, kind)
    assert engine.state.players[0].life==14
    assert source.attached_to=='p4' and source.controller_id=='p2'
    assert calls==[6,2]


@pytest.mark.parametrize('kind',['Creature','Artifact Creature'])
def test_creature_spell_does_not_trigger(kind):
    engine, source = _board()
    _cast(engine, kind)
    assert engine.state.players[0].life==20 and source.attached_to=='p1'


def test_other_caster_does_not_trigger():
    engine, source = _board()
    source.attached_to='p3'
    _cast(engine)
    assert engine.state.players[0].life==20 and source.attached_to=='p3'


def test_only_opponent_keeps_aura():
    engine, source = _board(players=2)
    _cast(engine)
    assert 14 <= engine.state.players[0].life <= 19
    assert source.attached_to=='p1'


@pytest.mark.parametrize('leave',['exile','return','reattach','steal'])
def test_trigger_keeps_firing_player_and_original_source_visit(leave):
    engine, source = _board()
    _cast(engine, resolve=False)
    if leave in ('exile','return'):
        engine.rules.exile(source)
        if leave=='return':
            engine.rules.return_from_graveyard(source, 'battlefield')
            source.attached_to='p3'
    elif leave=='reattach':
        source.attached_to='p3'
    else:
        source.controller_id='p4'
    engine.resolve_until_stable()
    assert 14 <= engine.state.players[0].life <= 19
    assert engine.state.players[2].life==20
    if leave=='exile':
        assert source.zone==Zone.EXILE
    elif leave=='return':
        assert source.attached_to=='p3'
    else:
        assert source.attached_to in ('p3','p4')


def test_clone_replays_same_roll_and_random_opponent():
    engine, source = _board()
    _cast(engine, resolve=False)
    clone = GameEngine(engine.state.clone())
    engine.resolve_until_stable()
    clone.resolve_until_stable()
    assert [p.life for p in engine.state.players]==[p.life for p in clone.state.players]
    assert source.attached_to==clone.state.find_object(source.instance_id).attached_to


def test_real_aura_cast_attaches_to_player():
    engine = game()
    advance_to(engine, 'main1')
    source = card(engine, 'Maddening Hex', zone=Zone.HAND)
    cast(engine, source, targets=[engine.state.players[1]])
    assert source.attached_to=='p2' and source.zone==Zone.BATTLEFIELD


@pytest.mark.parametrize('result',range(1,7))
def test_all_six_die_faces_are_damage_amounts(result, monkeypatch):
    engine, source = _board()
    draws = iter([result-1, 0])
    monkeypatch.setattr(engine.rules, 'random_int', lambda n: next(draws))
    _cast(engine)
    assert engine.state.players[0].life==20-result
    assert source.attached_to=='p3'


def test_multiple_pending_casts_damage_original_caster_after_aura_moves(monkeypatch):
    engine, source = _board()
    _cast(engine, resolve=False)
    _cast(engine, resolve=False)
    draws = iter([0,0,5,1])
    monkeypatch.setattr(engine.rules, 'random_int', lambda n: next(draws))
    engine.resolve_until_stable()
    assert engine.state.players[0].life==13
    assert all(p.life==20 for p in engine.state.players[1:])
    assert source.attached_to=='p4'


def test_excluded_opponents_are_not_random_candidates(monkeypatch):
    engine, source = _board()
    engine.state.players[2].has_lost=True
    calls=[]
    def random_int(n):
        calls.append(n)
        return 0
    monkeypatch.setattr(engine.rules, 'random_int', random_int)
    _cast(engine)
    assert calls==[6,1] and source.attached_to=='p4'
