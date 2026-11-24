"""Spell targeting, exact visits, indirect phasing, and phase-in Spirit tokens."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH, activate
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    king=card(engine,'King of the Oathbreakers')
    spirit=filler(engine,'Other Spirit',type_line='Creature — Spirit',power=2,toughness=3)
    return engine,king,spirit


def _cast(engine,target,player='p1'):
    spell=card(engine,'Giant Growth',player=player,zone=Zone.HAND)
    p=engine.state.player_by_id(player)
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p,spell,targets=[target])
    engine.rules.put_triggers_on_stack()
    return spell


def _tokens(engine):
    return [o for o in engine.state.permanents() if o.is_token and o.name=='Spirit']


def test_fresh_specs_binding_and_flying():
    engine,king,spirit=_board()
    a,b=specs_for(king.card),specs_for(king.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(king.triggered_abilities)==2 and combat.has(king,'flying')


@pytest.mark.parametrize('who',['self','spirit'])
@pytest.mark.parametrize('caster',['p1','p2'])
def test_any_players_spell_phases_out_the_targeted_own_spirit(who,caster):
    engine,king,spirit=_board()
    target=king if who=='self' else spirit
    original=target.zone_incarnation
    _cast(engine,target,caster)
    engine.resolve_until_stable()
    assert target.phased_out and target.zone==Zone.BATTLEFIELD
    assert target.zone_incarnation==original and target.damage_marked==0
    assert target.power==(3 if who=='self' else 2)
    assert not _tokens(engine)


@pytest.mark.parametrize('kind',['plain','opponent'])
def test_nonspirit_and_opponents_spirit_do_not_trigger(kind):
    engine,king,spirit=_board()
    target=filler(engine,'Target',type_line='Creature' if kind=='plain' else 'Creature — Spirit',
                  player='p1' if kind=='plain' else 'p2',power=2,toughness=3)
    _cast(engine,target)
    engine.resolve_until_stable()
    assert not target.phased_out and target.power==5


def test_activated_ability_does_not_phase_out_spirit():
    engine,king,spirit=_board()
    source=card(engine,'Prodigal Pyromancer')
    activate(engine,source,targets=[spirit])
    assert not spirit.phased_out and spirit.damage_marked==1


@pytest.mark.parametrize('change',['new_visit','source_leaves','clone'])
def test_pending_phase_out_uses_exact_trigger_subject(change):
    engine,king,spirit=_board()
    _cast(engine,spirit)
    if change=='new_visit':
        engine.rules.exile(spirit)
        engine.rules.return_from_graveyard(spirit,'battlefield')
    elif change=='source_leaves':
        engine.rules.exile(king)
    else:
        engine=GameEngine(engine.state.clone())
        spirit=engine.state.find_object(spirit.instance_id)
    engine.resolve_until_stable()
    assert spirit.phased_out==(change!='new_visit')


def test_attachments_phase_with_king_and_return_together_with_tokens():
    engine,king,spirit=_board()
    aura=card(engine,'Pacifism',player='p2')
    equipment=card(engine,'Short Sword')
    aura.attached_to=king.instance_id
    equipment.attached_to=king.instance_id
    king.counters['+1/+1']=2
    _cast(engine,king)
    engine.resolve_until_stable()
    for obj in [king,aura,equipment]:
        assert obj.phased_out
    assert aura.attached_to==king.instance_id and equipment.attached_to==king.instance_id
    assert aura.phased_out_with==king.instance_id
    advance_to(engine,'untap')
    assert king.phased_out  # p2's untap cannot return p1's King or its p2 Aura.
    for _ in range(3):
        if engine.state.active_player.id=='p1':
            break
        advance_to(engine,'main1')
        advance_to(engine,'untap')
    assert engine.state.active_player.id=='p1'
    engine.resolve_until_stable()
    assert all(not obj.phased_out for obj in [king,aura,equipment])
    assert aura.attached_to==king.instance_id and equipment.attached_to==king.instance_id
    assert king.counters['+1/+1']==2
    tokens=_tokens(engine)
    assert len(tokens)==1
    token=tokens[0]
    assert token.tapped and token.power==token.toughness==1 and combat.has(token,'flying')


def test_simultaneous_phase_in_counts_king_and_other_spirit():
    engine,king,spirit=_board()
    _cast(engine,spirit)
    engine.resolve_until_stable()
    _cast(engine,king)
    engine.resolve_until_stable()
    # Run the controller's actual untap action; both objects are visible
    # before either PHASED_IN event is dispatched.
    engine._step_untap()
    engine.resolve_until_stable()
    assert not king.phased_out and not spirit.phased_out
    assert len(_tokens(engine))==2 and all(o.tapped for o in _tokens(engine))


@pytest.mark.parametrize('player',['p1','p2'])
def test_spirit_filter_follows_kings_current_controller(player):
    engine,king,spirit=_board()
    king.controller_id='p2'
    spirit.controller_id=player
    _cast(engine,spirit)
    engine.resolve_until_stable()
    assert spirit.phased_out==(player=='p2')


def test_phasing_removes_attacker_from_combat_without_losing_counters():
    engine,king,spirit=_board()
    king.attacking=True
    king.combat_defender={'kind':'player','id':'p2'}
    king.counters['+1/+1']=1
    _cast(engine,king)
    engine.resolve_until_stable()
    assert king.phased_out and not king.attacking and king.combat_defender is None
    assert king.counters['+1/+1']==1


def test_phased_blocker_stops_blocking_but_attacker_stays_blocked():
    engine,king,spirit=_board()
    attacker=filler(engine,'Attacker',player='p2',power=2,toughness=2)
    attacker.attacking=True
    attacker.is_blocked=True
    attacker.blocked_by=[king.instance_id]
    king.blocking=attacker.instance_id
    _cast(engine,king)
    engine.resolve_until_stable()
    assert king.phased_out and king.blocking is None
    assert attacker.attacking and attacker.is_blocked and attacker.blocked_by==[]
