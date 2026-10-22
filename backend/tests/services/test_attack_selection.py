"""The board submits its edited attacker selection as one validated batch."""
import pytest

from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameActionError
from tests.services.test_bots import make_game, keep, bear


def setup():
    session = make_game()
    keep(session, 'ann', 'bob')
    engine = session.engine
    engine.state.current_step = 'declare_attackers'
    creatures = []
    for name in ['First', 'Second']:
        creature = GameObject(bear(name), owner_id='ann', zone=Zone.BATTLEFIELD)
        creature.summoning_sick = False
        engine.state.add_to_battlefield(creature)
        creatures.append(creature)
    engine.recompute_continuous_effects()
    return session, creatures


def test_one_batch_declares_only_selected_attackers():
    session, (a,b) = setup()
    session.apply_action({'type':'declare_attackers','declarations':[
        {'instance_id':b.instance_id,'defender':{'kind':'player','id':'bob'}}]}, actor_id='ann')
    assert b.attacking and b.tapped
    assert not a.attacking and not a.tapped


def test_invalid_or_duplicate_batch_does_not_partially_declare_attackers():
    session, (a,b) = setup()
    for picks in [[{'instance_id':a.instance_id}]*2,
                  [{'instance_id':a.instance_id},{'instance_id':b.instance_id,'defender':{'kind':'player','id':'ann'}}]]:
        with pytest.raises(GameActionError):
            session.apply_action({'type':'declare_attackers','declarations':picks},actor_id='ann')
        assert all(not session.engine.state.find_object(o.instance_id).attacking for o in (a,b))


def test_batch_accepts_different_defenders_in_one_declaration():
    from mtg_analyzer.models.cards.card import Card
    session, (a,b) = setup()
    walker = GameObject(Card(id='walker',name='Walker',type_line='Planeswalker',loyalty=4),owner_id='bob',zone=Zone.BATTLEFIELD)
    session.engine.state.add_to_battlefield(walker)
    walker.counters["loyalty"] = 4
    session.apply_action({'type':'declare_attackers','declarations':[
        {'instance_id':a.instance_id,'defender':{'kind':'player','id':'bob'}},
        {'instance_id':b.instance_id,'defender':{'kind':'planeswalker','instance_id':walker.instance_id}}]},actor_id='ann')
    assert a.combat_defender['id']=='bob'
    assert b.combat_defender['instance_id']==walker.instance_id
