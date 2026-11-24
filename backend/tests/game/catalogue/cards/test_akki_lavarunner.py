"""Akki Lavarunner's damage flip and Tok-Tok's symmetric red-player damage bonus."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Akki Lavarunner')
    return engine,source


def _hit(engine,source,target='p2',amount=1,combat_damage=False):
    victim=engine.state.player_by_id(target) if isinstance(target,str) else target
    engine.rules.deal_damage(victim,amount,source=source,combat=combat_damage)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def _flip(engine,source):
    _hit(engine,source)
    assert source.flipped and source.name=='Tok-Tok, Volcano Born'


def test_fresh_specs_front_binding_and_haste():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1 and not source.replacement_effects
    assert combat.has(source,'haste')


@pytest.mark.parametrize('combat_damage',[False,True])
def test_damage_to_opponent_flips_after_original_damage(combat_damage):
    engine,source=_board()
    _hit(engine,source,combat_damage=combat_damage)
    assert engine.state.players[1].life==19
    assert source.flipped and source.name=='Tok-Tok, Volcano Born'
    assert source.power==2 and source.toughness==2 and source.is_legendary
    assert not combat.has(source,'haste')
    assert len(source.replacement_effects)==1 and not source.triggered_abilities
    _hit(engine,source)
    assert engine.state.players[1].life==17


@pytest.mark.parametrize('kind',['own_player','creature','zero','other_source'])
def test_wrong_damage_does_not_flip(kind):
    engine,source=_board()
    if kind=='creature':
        target=filler(engine,player='p2',power=1,toughness=5)
        _hit(engine,source,target)
    elif kind=='other_source':
        _hit(engine,filler(engine,power=1,toughness=1))
    else:
        _hit(engine,source,target='p1' if kind=='own_player' else 'p2',amount=0 if kind=='zero' else 1)
    assert not source.flipped and combat.has(source,'haste')


@pytest.mark.parametrize('dealer',['p1','p2','p3'])
@pytest.mark.parametrize('recipient',['p1','p2'])
def test_any_red_source_gets_bonus_to_any_player(dealer,recipient):
    engine,source=_board()
    _flip(engine,source)
    red=card(engine,'Prodigal Pyromancer',player=dealer)
    before=engine.state.player_by_id(recipient).life
    _hit(engine,red,recipient,amount=2)
    assert engine.state.player_by_id(recipient).life==before-3


@pytest.mark.parametrize('kind',['nonred','permanent','zero'])
def test_bonus_requires_positive_red_damage_to_player(kind):
    engine,source=_board()
    _flip(engine,source)
    red=card(engine,'Prodigal Pyromancer')
    if kind=='permanent':
        target=filler(engine,player='p2',power=1,toughness=5)
        _hit(engine,red,target,amount=2)
        assert target.damage_marked==2
    else:
        dealer=filler(engine,power=1,toughness=1) if kind=='nonred' else red
        before=engine.state.players[1].life
        _hit(engine,dealer,amount=0 if kind=='zero' else 2)
        assert engine.state.players[1].life==before-(2 if kind=='nonred' else 0)


def test_red_protection_prevents_red_damage_to_tok_tok():
    engine,source=_board()
    _flip(engine,source)
    red=card(engine,'Prodigal Pyromancer',player='p2')
    _hit(engine,red,source,amount=3)
    assert source.zone==Zone.BATTLEFIELD and source.damage_marked==0


def test_clone_preserves_flip_and_replacement():
    engine,source=_board()
    _flip(engine,source)
    engine=GameEngine(engine.state.clone())
    source=engine.state.find_object(source.instance_id)
    _hit(engine,source,'p3')
    assert source.flipped and engine.state.players[2].life==18


def test_leave_and_return_uses_front_face_again():
    engine,source=_board()
    _flip(engine,source)
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert not source.flipped and source.name.startswith('Akki Lavarunner')
    assert combat.has(source,'haste') and not source.replacement_effects


def test_pending_flip_cannot_flip_a_returned_new_visit():
    engine,source=_board()
    engine.rules.deal_damage(engine.state.players[1],1,source=source)
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert not source.flipped



def test_real_combat_attack_flips_after_dealing_one_damage():
    engine,source=_board()
    source.summoning_sick=True
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(engine.state.players[0],[{'attacker':source,'defender':engine.state.players[1]}])
    advance_to(engine,'main2')
    assert source.flipped and engine.state.players[1].life==19
    assert source.power==2 and source.toughness==2


def test_back_face_specs_are_fresh():
    engine,source=_board()
    _flip(engine,source)
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0].ability_kind=='replacement' and a[0] is not b[0]
    assert a[0].effects[0] is not b[0].effects[0]
