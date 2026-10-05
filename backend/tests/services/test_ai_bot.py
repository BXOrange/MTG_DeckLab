"""AI choices stay within offered actions; slow/failed calls retain safe gameplay."""
import threading
import pytest
from mtg_analyzer.services.bots import AIBot, SmartBot, _one_bot_action
from mtg_analyzer.services.bot_policies.ai import BotDecision
from mtg_analyzer.services.bot_strategy import build_strategy
from mtg_analyzer.services.llm_settings import LLMSettings
from mtg_analyzer.services.llm_client import LLMError
from tests.services.test_smart_bot import view, obj, spell
from tests.services.test_bots import make_game, keep, land

class Settings:
    def get(self):
        return LLMSettings(enabled=True, model='mock', api_key='secret', bot_calls_per_turn=2)

class Client:
    def __init__(self, fail=False):
        self.payloads = []
        self.fail = fail
    def generate(self, settings, system, payload, output):
        self.payloads.append(payload)
        if self.fail:
            raise LLMError('Unavailable')
        return output(offer_index=next((i for i,a in enumerate(payload['offers']) if a['type'] == 'play_land'), 0))

def bot(client=None):
    result = AIBot('ann', client=client or Client(), settings_store=Settings())
    result.strategy = build_strategy([land(), spell('Engine')], [], [])
    return result

def actions():
    return [{'type': 'play_land', 'instance_id': 1}, {'type': 'pass_priority'}]

def test_background_decision_does_not_pass_and_receives_redacted_deck_context():
    client = Client()
    b = bot(client)
    v = view(hand=[obj(1, 'Forest')])
    assert b.decide(v, actions()) is None
    assert b.waiting
    b.context['future'].result(timeout=5)
    assert b.decide(v, actions()) == actions()[0]
    assert not b.waiting
    payload = client.payloads[0]
    assert payload['state']['players'][1]['hand'] == []
    assert payload['state']['players'][0]['library'] == []
    assert payload['deck']['identity'] == ['G']
    assert any(c['name'] == 'Engine' for c in payload['deck']['cards'])
    assert 'secret' not in str(payload)

def test_pending_driver_preserves_priority_and_context_survives_bot_rebuild():
    session = make_game()
    keep(session, 'ann', 'bob')
    class SlowClient(Client):
        def generate(self, *args):
            assert gate.wait(5)
            return super().generate(*args)
    gate = threading.Event()
    b = bot(SlowClient())
    # Step through forced passes until there is a real offered land choice.
    for _ in range(40):
        if any(a['type'] == 'play_land' for a in session.legal_actions(perspective='ann')):
            break
        from mtg_analyzer.services.bots import GoldfishBot
        _one_bot_action(session, {'ann': GoldfishBot('ann'), 'bob': GoldfishBot('bob')})
    try:
        before = session.engine.state.priority_player.id
        assert not _one_bot_action(session, {'ann': b})
        assert b.waiting
        assert session.engine.state.priority_player.id == before == 'ann'
        rebuilt = bot()
        rebuilt.prepare(session)
        assert rebuilt.context is b.context
    finally:
        gate.set()
        if b.context.get('future'):
            b.context['future'].result(timeout=5)
    assert _one_bot_action(session, {'ann': rebuilt})
    assert any(o.is_land for o in session.engine.state.battlefield)

def test_provider_failure_falls_back_once_per_position():
    client = Client(fail=True)
    b = bot(client)
    v = view(hand=[obj(1, 'Forest')])
    b.decide(v, actions())
    with pytest.raises(LLMError):
        b.context['future'].result(timeout=5)
    assert b.decide(v, actions())['type'] == 'play_land'
    assert b.status['status'] == 'fallback'
    assert b.decide(v, actions())['type'] == 'play_land'
    assert len(client.payloads) == 1

def test_stale_completed_result_is_discarded_and_turn_budget_is_bounded():
    b = bot()
    v = view(hand=[obj(1, 'Forest')])
    b.decide(v, actions())
    b.context['future'].result(timeout=5)
    updated = actions()[0] | {'instance_id': 2}
    new_view = view(hand=[obj(2, 'Forest')])
    assert b.decide(new_view, [updated, actions()[1]]) is None
    b.context['future'].result(timeout=5)
    assert b.decide(new_view, [updated, actions()[1]]) == updated
    third = view(hand=[obj(3, 'Forest')])
    assert b.decide(third, [updated | {'instance_id':3}, actions()[1]])['instance_id'] == 3
    assert b.status['status'] == 'fallback'
    assert len(b.client.payloads) == 2

@pytest.mark.parametrize('decision', [dict(offer_index=4), dict(offer_index=0, target_indices=[[-1]]),
    dict(offer_index=0, target_indices=[[0,0]]), dict(offer_index=0, x=10)])
def test_unoffered_actions_targets_and_x_are_rejected(decision):
    offer = {'type':'cast_spell','instance_id':1, 'requires_target':True,
             'targets':[{'count':1, 'options':[{'instance_id':2}]}], 'has_x':True,'max_x':2}
    with pytest.raises((ValueError, IndexError)):
        bot().complete_decision(view(), [offer], BotDecision(**decision))

def test_explicit_targets_attackers_and_blocks_are_completed():
    b = bot()
    offer = {'type':'cast_spell','instance_id':1, 'requires_target':True,
             'targets':[{'count':1, 'options':[{'instance_id':2},{'instance_id':3}]}]}
    assert b.complete_decision(view(), [offer], BotDecision(offer_index=0, target_indices=[[1]]))['targets'] == [{'instance_id':3}]
    defender = {'kind':'player','id':'bob'}
    attacks = [{'type':'attack','instance_id':i,'legal_defenders':[defender]} for i in (1,2)]
    assert b.complete_decision(view(), attacks, BotDecision(offer_index=0, attacker_ids=[1,2]))['instance_ids'] == [1,2]
    blocks = [{'type':'declare_blockers','instance_id':1,'legal_attackers':[{'instance_id':2}]}]
    assert b.complete_decision(view(), blocks, BotDecision(offer_index=0, blocks=[{'blocker':1,'attacker':2}]))['assignments'] == [{'blocker':1,'attacker':2}]
    with pytest.raises(ValueError):
        b.complete_decision(view(), blocks, BotDecision(offer_index=0, blocks=[{'blocker':1,'attacker':9}]))

def test_bot_public_imports_preserved():
    from mtg_analyzer.services.bot_policies.smart import SmartBot as IndividualSmart
    from mtg_analyzer.services.bot_policies.greedy import GreedyBot
    from mtg_analyzer.services import bots
    assert IndividualSmart is SmartBot
    assert bots.GreedyBot is GreedyBot
    assert bots.create_bot('ai', 'ann').kind == 'ai'


def test_llm_policy_develops_mana_and_casts_a_creature_through_real_engine():
    import random
    from tests.services.test_bots import bear
    from mtg_analyzer.services.bots import GoldfishBot
    class PlayingClient(Client):
        def generate(self, settings, system, payload, output):
            self.payloads.append(payload)
            for kind in ('cast_spell', 'play_land', 'pass_priority'):
                for i, offer in enumerate(payload['offers']):
                    if offer['type'] == kind:
                        self.selected.append(kind)
                        return output(offer_index=i)
            return output(offer_index=0)
    random.seed(3)
    session = make_game(ann_deck=[land()] * 20 + [bear()] * 15)
    keep(session, 'ann', 'bob')
    client = PlayingClient()
    client.selected = []
    policy = bot(client)
    class PlayingSettings(Settings):
        def get(self):
            return super().get().model_copy(update={'bot_calls_per_turn':32})
    policy.settings_store = PlayingSettings()
    policies = {'ann':policy, 'bob':GoldfishBot('bob')}
    for _ in range(800):
        _one_bot_action(session, policies)
        if policy.context.get('future'):
            policy.context['future'].result(timeout=5)
        if any(o.is_creature and o.controller_id == 'ann' for o in session.engine.state.battlefield):
            break
    assert 'play_land' in client.selected
    assert 'cast_spell' in client.selected
    assert any(o.is_creature and o.controller_id == 'ann' for o in session.engine.state.battlefield)


def test_manual_display_actions_do_not_spend_llm_budget_on_a_forced_pass():
    policy = bot()
    policy.decide(view(), [{'type':'pass_priority'}, {'type':'toggle_tapped','instance_id':1}])
    assert not policy.waiting
    assert not policy.client.payloads
    assert not policy.context.get('future')


def test_rejected_action_reason_reaches_next_request_and_survives_rebuild():
    client = Client()
    b = bot(client)
    session = make_game()
    b.prepare(session)
    v = view(hand=[obj(1, 'Forest')])
    b.decide(v, actions())
    b.context['future'].result(timeout=5)
    rejected = b.decide(v, actions())
    b.note_failure(rejected, 'Dieses Land kann jetzt nicht gespielt werden.')
    rebuilt = bot(client)
    rebuilt.prepare(session)
    assert rebuilt.decide(v, actions()) is None
    assert rebuilt.waiting
    rebuilt.context['future'].result(timeout=5)
    assert client.payloads[-1]['action_feedback'] == [
        {'action': rejected, 'reason': 'Dieses Land kann jetzt nicht gespielt werden.'}]
    assert actions()[0] in client.payloads[-1]['offers']
    rebuilt.decide(v, actions())
    # A new position must not retain stale rejection messages.
    rebuilt.decide(view(hand=[obj(2, 'Forest')]), [{'type':'play_land','instance_id':2}, actions()[1]])
    assert rebuilt.action_feedback == []


def test_driver_retries_rejected_action_without_passing(monkeypatch):
    from mtg_analyzer.services.bots import Bot
    from mtg_analyzer.services.game_session import GameActionError
    session = make_game()
    keep(session, 'ann', 'bob')
    class CorrectingBot(Bot):
        def decide(self, view, actions):
            if not self.action_feedback:
                return {'type':'play_land', 'instance_id':-1}
            assert self.action_feedback[-1]['reason'] == 'Karte nicht verfügbar'
            return {'type':'toggle_tapped', 'instance_id':123}
    applied = []
    def apply(action, actor_id):
        applied.append(action)
        if len(applied) == 1:
            raise GameActionError('Karte nicht verfügbar')
    monkeypatch.setattr(session, 'apply_action', apply)
    assert _one_bot_action(session, {'ann':CorrectingBot('ann')})
    assert [a['type'] for a in applied] == ['play_land', 'toggle_tapped']


def test_repeated_rejections_are_bounded_and_reset_for_new_position():
    b = bot()
    v = view(hand=[obj(1, 'Forest')])
    b.decide(v, actions())
    b.context['future'].result(timeout=5)
    b.decide(v, actions())
    for _ in range(3):
        b.note_failure(actions()[0], 'Nicht erlaubt')
    assert b.decide(v, actions()) in (None, {'type':'pass_priority'})
    assert not b.waiting
    assert len(b.client.payloads) == 1
    b.decide(view(hand=[obj(2, 'Forest')]), [{'type':'play_land','instance_id':2}, actions()[1]])
    b.context['future'].result(timeout=5)
    assert b.client.payloads[-1]['action_feedback'] == []
