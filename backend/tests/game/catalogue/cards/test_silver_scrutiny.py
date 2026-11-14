"""Silver Scrutiny uses the proposed X for timing and the paid X for drawing."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, RICH
from tests.support.star_trek import advance_to


def _board(off_turn=False):
    engine=game(players=3,library=40)
    advance_to(engine,'main1')
    spell=card(engine,'Silver Scrutiny',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    if off_turn:
        engine.state.active_player_index=1
        engine.state.current_step='end'
    return engine,spell,p


def test_fresh_specs_and_binding():
    engine,spell,p=_board()
    a,b=specs_for(spell.card),specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert spell.conditional_flash=={'active_if':{'kind':'x_paid','max':3}}


@pytest.mark.parametrize('x',[0,1,2,3,4,5])
def test_flash_timing_uses_announced_x_and_leaves_preview_state_unchanged(x):
    engine,spell,p=_board(True)
    spell.x_paid=9
    before=p.mana_pool.to_dict()
    assert engine.can_cast(p,spell,x=x)==(x<=3)
    assert spell.x_paid==9 and p.mana_pool.to_dict()==before
    assert spell.zone==Zone.HAND and not engine.state.stack


@pytest.mark.parametrize('x',[0,1,3,4,7])
def test_main_phase_cast_draws_exactly_x_cards(x):
    engine,spell,p=_board()
    hand=len(p.hand)
    library=len(p.library)
    engine.cast_spell(p,spell,x=x)
    engine.resolve_until_stable()
    assert len(p.hand)==hand-1+x and len(p.library)==library-x
    assert spell.zone==Zone.GRAVEYARD


@pytest.mark.parametrize('x',[0,3])
def test_off_turn_cast_resolves_at_allowed_boundary(x):
    engine,spell,p=_board(True)
    before=len(p.library)
    engine.cast_spell(p,spell,x=x)
    engine.resolve_until_stable()
    assert len(p.library)==before-x and spell.zone==Zone.GRAVEYARD


def test_illegal_off_turn_x_four_is_rejected_without_payment():
    engine,spell,p=_board(True)
    before=p.mana_pool.to_dict()
    with pytest.raises(ValueError):
        engine.cast_spell(p,spell,x=4)
    assert spell.zone==Zone.HAND and p.mana_pool.to_dict()==before and not engine.state.stack


def test_countering_spell_draws_nothing():
    engine,spell,p=_board()
    before=len(p.library)
    engine.cast_spell(p,spell,x=3)
    engine.rules.counter_spell(spell)
    engine.resolve_until_stable()
    assert len(p.library)==before and spell.zone==Zone.GRAVEYARD


def test_clone_preserves_announced_x_for_resolution():
    engine,spell,p=_board()
    engine.cast_spell(p,spell,x=5)
    before=len(p.library)
    clone=GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert len(clone.state.player_by_id('p1').library)==before-5
    assert len(p.library)==before


def test_external_flash_permission_allows_x_above_three():
    engine,spell,p=_board(True)
    card(engine,'Vedalken Orrery')
    engine.recompute_continuous_effects()
    assert engine.can_cast(p,spell,x=4)
    before=len(p.library)
    engine.cast_spell(p,spell,x=4)
    engine.resolve_until_stable()
    assert len(p.library)==before-4
