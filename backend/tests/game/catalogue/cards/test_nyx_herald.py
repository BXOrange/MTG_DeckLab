"""Nyx Herald's union target includes itself and rechecks eligibility."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Nyx Herald')
    return engine,source


def _trigger(engine):
    advance_to(engine,'begin_combat')
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    return engine.state.pending_choice


def _pick(engine,obj,pause=False):
    choice=engine.state.pending_choice
    option=next(o for o in choice['options'] if o.get('instance_id')==obj.instance_id)
    if pause:
        engine.rules.resolve_choice(option['id'])
    else:
        engine.resolve_pending_choice(option['id'])
        engine.resolve_until_stable()


def test_fresh_specs_and_binding():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1


@pytest.mark.parametrize('kind',['self','enchantment','enchanted'])
def test_both_branches_and_self_receive_pump(kind):
    engine,source=_board()
    target=source if kind=='self' else card(engine,'Nyxborn Courser') if kind=='enchantment' else filler(engine,'Bearer',power=2,toughness=3)
    if kind=='enchanted':
        aura=card(engine,'Pacifism',player='p2')
        aura.attached_to=target.instance_id
    engine.recompute_continuous_effects()
    before=(target.power,target.toughness)
    _trigger(engine)
    _pick(engine,target)
    assert (target.power,target.toughness)==(before[0]+1,before[1]+1)
    assert combat.has(target,'trample')
    advance_to(engine,'cleanup')
    assert (target.power,target.toughness)==before and not combat.has(target,'trample')


def test_plain_equipped_and_opponent_creatures_are_not_targets():
    engine,source=_board()
    plain=filler(engine,'Plain',power=2,toughness=2)
    equipped=filler(engine,'Equipped',power=2,toughness=2)
    equipment=card(engine,'Short Sword')
    equipment.attached_to=equipped.instance_id
    opponent=card(engine,'Nyxborn Courser',player='p2')
    noncreature=card(engine,'Levitation')
    choice=_trigger(engine)
    ids={o.get('instance_id') for o in choice['options']}
    assert source.instance_id in ids
    assert not ids.intersection({o.instance_id for o in [plain,equipped,opponent,noncreature]})


@pytest.mark.parametrize('change',['aura_leaves','control','new_visit'])
def test_target_legality_is_rechecked(change):
    engine,source=_board()
    target=filler(engine,'Bearer',power=2,toughness=3)
    aura=card(engine,'Pacifism')
    aura.attached_to=target.instance_id
    _trigger(engine)
    _pick(engine,target,pause=True)
    if change=='aura_leaves':
        engine.rules.exile(aura)
    elif change=='control':
        target.controller_id='p2'
    else:
        engine.rules.exile(target)
        engine.rules.return_from_graveyard(target,'battlefield')
    engine.resolve_until_stable()
    assert target.power==2 and not combat.has(target,'trample')


def test_opponents_combat_does_not_trigger():
    engine,source=_board()
    engine.state.active_player_index=1
    _trigger(engine)
    assert not engine.state.stack and engine.state.pending_choice is None


@pytest.mark.parametrize('change',['source_leaves','clone','aura_leaves'])
def test_pending_pump_survives_source_loss_or_clone_and_either_branch_is_enough(change):
    engine,source=_board()
    target=card(engine,'Nyxborn Courser')
    aura=card(engine,'Pacifism')
    aura.attached_to=target.instance_id
    before=(target.power,target.toughness)
    _trigger(engine)
    _pick(engine,target,pause=True)
    if change=='source_leaves':
        engine.rules.exile(source)
    elif change=='clone':
        engine=GameEngine(engine.state.clone())
        target=engine.state.find_object(target.instance_id)
    else:
        engine.rules.exile(aura)
    engine.resolve_until_stable()
    assert (target.power,target.toughness)==(before[0]+1,before[1]+1)
    assert combat.has(target,'trample')
