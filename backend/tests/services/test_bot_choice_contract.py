"""Bot decisions stay within offered answers, including Kodama's live search."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.bots import Bot, SmartBot, _one_bot_action
from mtg_analyzer.services.bot_policies.smart2 import SmartBot2
from tests.services.test_bots import make_game, keep


def _permanent(session, name, controller, creature=False):
    card = Card(id=name, name=name, type_line='Creature — Spirit' if creature else 'Enchantment — Aura',
                is_creature=creature, power=1 if creature else None, toughness=3 if creature else None)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    session.engine.state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize('policy', [SmartBot, SmartBot2])
def test_kodama_combat_search_is_offered_to_bot_while_human_holds_priority(policy):
    session = make_game()
    keep(session, 'ann', 'bob')
    state = session.engine.state
    state.active_player_index = 1
    state.priority_player_index = 0
    state.current_phase = 'combat'
    state.current_step = 'combat_damage'
    kodama = _permanent(session, 'Kodama of the West Tree', 'bob', True)
    kodama.tapped = True
    aura = _permanent(session, 'Bear Umbra', 'bob')
    aura.attached_to = kodama.instance_id
    opposing_aura = _permanent(session, 'Betrayal', 'ann')
    opposing_aura.attached_to = kodama.instance_id
    session.engine.recompute_continuous_effects()
    session.engine.rules.deal_damage(state.players[0], 3, source=kodama, combat=True)
    session.engine.rules.put_triggers_on_stack()
    for _ in range(10):
        if state.pending_choice:
            break
        session.apply_action({'type': 'pass_priority'}, actor_id=state.priority_player.id)
    assert state.pending_choice['kind'] == 'search'
    assert state.pending_choice['player_id'] == 'bob'
    # Match the report: the retained priority marker belongs to the human,
    # while the resolving choice belongs to the bot.
    state.priority_player_index = 0
    assert state.priority_player.id == 'ann'
    human = session.view(perspective='ann')
    assert human['pending_choice'] is None
    assert not human['legal_actions']
    bot = policy('bob')
    bot.prepare(session)
    view = session.view(perspective='bob')
    assert not view['state']['players'][1]['library']  # offered names authorize the search, not library order
    actions = session.legal_actions(perspective='bob')
    answer = bot.decide(view, actions)
    assert answer in actions and answer['type'] == 'choose'
    picked = answer['instance_id']
    assert _one_bot_action(session, {'bob': bot})
    assert state.find_object(picked).zone == Zone.BATTLEFIELD
    assert state.find_object(picked).tapped
    assert not state.pending_choice or state.pending_choice['kind'] != 'search'
    assert not bot.action_feedback


@pytest.mark.parametrize('answer', [None, {'type': 'choose', 'option_id': 'invented'}, {'type': 'decline'}])
def test_invalid_policy_answer_falls_back_to_mandatory_offered_option(answer):
    class FaultyPolicy(Bot):
        def answer_choice(self, view, answers):
            return answer
    session = make_game()
    keep(session, 'ann', 'bob')
    player = session.engine.state.players[1]
    session.engine.rules._request_choose_objects(player, list(player.hand), 'hand_to_library_top', count=1)
    bot = FaultyPolicy('bob')
    assert _one_bot_action(session, {'bob': bot})
    assert session.engine.state.pending_choice is None
    assert bot.action_feedback[-1]['reason'] == 'Bot choice was not offered'


def test_choice_uses_offered_identity_and_retains_async_waiting():
    class Policy(Bot):
        def answer_choice(self, view, answers):
            return {'type': 'choose', 'option_id': 17, 'instance_id': 999}
    bot = Policy('bob')
    offer = {'type': 'choose', 'option_id': '17', 'instance_id': 17}
    assert bot.decide({'pending_choice': {'kind': 'search'}}, [offer]) == offer
    bot.waiting = True
    bot.answer_choice = lambda view, answers: None
    assert bot.decide({}, [offer]) is None
