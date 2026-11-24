"""Scouring's optional flying-creature tap cost and ordered wipe/token creation."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def _board(off_turn=True,count=4):
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    spell=card(engine,"Tegwyll's Scouring",zone=Zone.HAND)
    flyers=[filler(engine,f'Flyer {i}',power=1,toughness=2,keywords=['flying']) for i in range(count)]
    other=filler(engine,'Opponent',player='p2',power=3,toughness=3)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    if off_turn:
        engine.state.active_player_index=1
        engine.state.current_step='end'
    return engine,spell,flyers,other,p


def _tokens(engine):
    return [o for o in engine.state.permanents() if o.is_token]


def test_fresh_specs_and_binding():
    engine,spell,flyers,other,p=_board()
    a,b=specs_for(spell.card),specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[1] is not b[0].effects[1]
    assert spell.additional_cast_cost.tap_others==(3,'creature_flying')
    assert spell.additional_cast_cost_optional


def test_off_turn_flash_requires_paid_additional_cost():
    engine,spell,flyers,other,p=_board()
    picks=[o.instance_id for o in flyers[1:]]
    assert not engine.can_cast(p,spell)
    assert engine.can_cast(p,spell,pay_additional=True,tap_choices=picks)
    assert all(not o.tapped for o in flyers) and not spell.additional_cost_paid
    engine.cast_spell(p,spell,pay_additional=True,tap_choices=picks)
    assert not flyers[0].tapped and all(o.tapped for o in flyers[1:])
    engine.resolve_until_stable()
    assert all(o.zone==Zone.GRAVEYARD for o in [*flyers,other])
    tokens=_tokens(engine)
    assert len(tokens)==3
    for token in tokens:
        assert token.controller_id=='p1' and token.power==token.toughness==1
        assert token.colors=={'B'} and token.has_subtype('Faerie') and token.has_subtype('Rogue')
        assert combat.has(token,'flying')


@pytest.mark.parametrize('invalid',['tapped','opponent','nonflying','duplicate','two','four'])
def test_invalid_explicit_tap_selection_cannot_pay(invalid):
    engine,spell,flyers,other,p=_board()
    picks=[o.instance_id for o in flyers[:3]]
    if invalid=='tapped':
        flyers[0].tapped=True
    elif invalid=='opponent':
        flyers[0].controller_id='p2'
    elif invalid=='nonflying':
        picks[0]=other.instance_id
        other.controller_id='p1'
    elif invalid=='duplicate':
        picks[1]=picks[0]
    elif invalid=='two':
        picks=picks[:2]
    else:
        picks=[o.instance_id for o in flyers]
    before=p.mana_pool.to_dict()
    assert not engine.can_cast(p,spell,pay_additional=True,tap_choices=picks)
    with pytest.raises(ValueError):
        engine.cast_spell(p,spell,pay_additional=True,tap_choices=picks)
    assert spell.zone==Zone.HAND and p.mana_pool.to_dict()==before


def test_main_phase_cast_needs_no_flying_creatures():
    engine,spell,flyers,other,p=_board(False,0)
    assert engine.can_cast(p,spell)
    engine.cast_spell(p,spell)
    engine.resolve_until_stable()
    assert other.zone==Zone.GRAVEYARD and len(_tokens(engine))==3


def test_fewer_than_three_flyers_cannot_supply_flash():
    engine,spell,flyers,other,p=_board(count=2)
    assert not engine.can_cast(p,spell,pay_additional=True)


def test_summoning_sick_flyers_can_pay_non_symbol_tap_cost():
    engine,spell,flyers,other,p=_board(count=3)
    for flyer in flyers:
        flyer.summoning_sick=True
    engine.cast_spell(p,spell,pay_additional=True,tap_choices=[o.instance_id for o in flyers])
    assert all(o.tapped for o in flyers)


def test_countering_spell_keeps_tap_cost_paid_and_creates_no_tokens():
    engine,spell,flyers,other,p=_board(count=3)
    engine.cast_spell(p,spell,pay_additional=True,tap_choices=[o.instance_id for o in flyers])
    engine.rules.counter_spell(spell)
    engine.resolve_until_stable()
    assert all(o.tapped and o.zone==Zone.BATTLEFIELD for o in flyers)
    assert not _tokens(engine)


def test_clone_preserves_paid_cast_and_resulting_tokens():
    engine,spell,flyers,other,p=_board(count=3)
    engine.cast_spell(p,spell,pay_additional=True,tap_choices=[o.instance_id for o in flyers])
    clone=GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert len(_tokens(clone))==3 and not _tokens(engine)
    assert clone.state.find_object(other.instance_id).zone==Zone.GRAVEYARD


def test_independent_flash_permission_does_not_require_tapping():
    engine,spell,flyers,other,p=_board(count=0)
    card(engine,'Vedalken Orrery')
    engine.recompute_continuous_effects()
    assert engine.can_cast(p,spell)
    engine.cast_spell(p,spell)
    engine.resolve_until_stable()
    assert len(_tokens(engine))==3


def test_stale_paid_flag_does_not_authorize_unpaid_proposal():
    engine,spell,flyers,other,p=_board()
    spell.additional_cost_paid=True
    assert not engine.can_cast(p,spell,pay_additional=False)
    assert spell.additional_cost_paid is True and all(not o.tapped for o in flyers)


def test_card_spec_roundtrip_preserves_optional_tap_cost_and_timing():
    from mtg_analyzer.parser.oracle.spec import AbilitySpec
    engine,spell,flyers,other,p=_board()
    spec=specs_for(spell.card)[0]
    restored=AbilitySpec.from_dict(spec.to_dict())
    assert restored.additional_cost=={'tap_others':[3,'creature_flying']}
    assert restored.additional_cost_optional and restored.conditional_flash==spec.conditional_flash
