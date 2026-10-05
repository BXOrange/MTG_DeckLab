"""LLM credentials, provider contracts and persistent ANA-1 cache."""
import json
from concurrent.futures import ThreadPoolExecutor
import httpx2 as httpx
import pytest
from pydantic import BaseModel
from mtg_analyzer.services.llm_client import LLMClient, LLMError
from mtg_analyzer.services.llm_settings import LLMSettings, LLMSettingsPatch, LLMSettingsStore
from mtg_analyzer.services.narrative_analysis import AnalysisDatabase, NarrativeAnalysis
from mtg_analyzer.models.analysis.narrative import NarrativeResult

RESULT = dict(summary='A green creature deck.', archetype='Ramp', win_conditions=['Combat'],
              synergies=['Mana development'], cohesion_score=70, issues=[], recommendations=[])

class FakeNarrator:
    def __init__(self):
        self.calls = []
    def generate(self, settings, system, payload, output):
        self.calls.append(payload)
        return output.model_validate(RESULT)

def store(tmp_path):
    settings = LLMSettingsStore(tmp_path / 'llm.json')
    settings.update(LLMSettingsPatch(enabled=True, model='test-model', api_key='secret'))
    return settings

def test_settings_secret_preservation_permissions_environment_and_clear(tmp_path, monkeypatch):
    settings = store(tmp_path)
    assert 'secret' not in json.dumps(settings.get().public())
    assert 'api_key' not in settings.get().public()
    assert settings.path.stat().st_mode & 0o777 == 0o600
    settings.update(LLMSettingsPatch(api_key='', model='new-model'))
    assert settings.get().api_key == 'secret'
    monkeypatch.setenv('MTG_LLM_MODEL', 'environment-model')
    monkeypatch.setenv('MTG_LLM_ENABLED', 'false')
    assert settings.get().model == 'environment-model'
    assert not settings.get().ready
    settings.update(LLMSettingsPatch(clear_api_key=True))
    assert not settings.get().public()['api_key_configured']

@pytest.mark.parametrize('url', ['file:///tmp/key', 'https://user:key@example.org', 'https://example.org/?key=secret'])
def test_settings_reject_embedded_credentials_and_non_http_urls(url):
    with pytest.raises(ValueError):
        LLMSettings(base_url=url)

class Answer(BaseModel):
    connected: bool

@pytest.mark.parametrize('provider', ['anthropic', 'compatible'])
def test_provider_transport_and_json_validation(provider):
    def respond(request):
        body = json.loads(request.content)
        assert body['model'] == 'test-model'
        if provider == 'anthropic':
            assert request.url.path == '/v1/messages'
            assert request.headers['x-api-key'] == 'secret'
            assert body['tool_choice']['name'] == 'submit_result'
            assert 'connected' in body['tools'][0]['input_schema']['properties']
            result = {'content': [{'type': 'tool_use', 'name': 'submit_result', 'input': {'connected': True}}]}
        else:
            assert request.url.path == '/v1/chat/completions'
            assert request.headers['Authorization'] == 'Bearer secret'
            assert body['response_format']['type'] == 'json_object'
            result = {'choices': [{'message': {'content': '{"connected":true}'}}]}
        return httpx.Response(200, json=result)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        settings = LLMSettings(enabled=True, provider=provider, model='test-model', api_key='secret')
        assert LLMClient(http).generate(settings, 'Test', {'card': 'untrusted'}, Answer).connected

@pytest.mark.parametrize('status,body', [(401, {'secret': 'do not expose'}), (200, {'content': ['bad']}),
                                        (200, {'content': [{'type':'tool_use','name':'submit_result','input':{}}]})])
def test_provider_errors_are_sanitized(status, body):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))) as http:
        with pytest.raises(LLMError) as caught:
            LLMClient(http).generate(LLMSettings(enabled=True, model='test-model', api_key='secret'), '', {}, Answer)
        assert 'secret' not in str(caught.value)

@pytest.mark.parametrize('operation', ['generate', 'list_models'])
@pytest.mark.parametrize('body,headers,expected', [
    ({'error': {'code': 'insufficient_quota', 'message': 'secret'}}, {}, 'API-Kontingent'),
    ({'error': {'type': 'insufficient_quota', 'message': 'secret'}}, {}, 'API-Kontingent'),
    ({'error': {'code': 'rate_limit_exceeded', 'message': 'secret'}},
     {'retry-after': '12'}, 'Nach 12 Sekunden'),
    ({'error': 'secret'}, {'retry-after': 'secret'}, 'Später erneut'),
    (['secret'], {}, 'Später erneut'),
])
def test_429_actionable_sanitized_errors(operation, body, headers, expected):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(429, json=body, headers=headers)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = LLMClient(http)
        settings = LLMSettings(enabled=True, provider='compatible', model='test-model', api_key='secret')
        with pytest.raises(LLMError) as caught:
            if operation == 'generate':
                client.generate(settings, '', {}, Answer)
            else:
                client.list_models(settings)
        assert expected in str(caught.value)
        assert 'HTTP 429' in str(caught.value)
        assert 'secret' not in str(caught.value)
        assert len(requests) == 1


def test_narrative_cache_singleflight_persistence_invalidation_and_force(tmp_path):
    settings, client = store(tmp_path), FakeNarrator()
    database = AnalysisDatabase(tmp_path / 'analyses.db')
    service = NarrativeAnalysis(database, settings, client)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: service.analyze('deck', {'mainboard_text': '1 Forest'}), range(2)))
    assert len(client.calls) == 1
    assert results[0]['id'] == results[1]['id']
    assert sorted(r['cached'] for r in results) == [False, True]
    assert 'secret' not in json.dumps(results)
    database.close()
    database = AnalysisDatabase(tmp_path / 'analyses.db')
    service = NarrativeAnalysis(database, settings, client)
    assert service.analyze('deck', {'mainboard_text': '1 Forest'})['cached']
    assert not service.analyze('deck', {'mainboard_text': '2 Forest'})['cached']
    settings.update(LLMSettingsPatch(model='other-model'))
    assert not service.analyze('deck', {'mainboard_text': '2 Forest'})['cached']
    assert not service.analyze('deck', {'mainboard_text': '2 Forest'}, force=True)['cached']
    assert len(client.calls) == 4
    database.close()

def test_invalid_narrative_is_never_persisted(tmp_path):
    class InvalidClient:
        def generate(self, *args):
            raise LLMError('Invalid result')
    database = AnalysisDatabase()
    with pytest.raises(LLMError):
        NarrativeAnalysis(database, store(tmp_path), InvalidClient()).analyze('deck', {})
    assert database.connection.execute('SELECT count(*) FROM analyses').fetchone()[0] == 0
    database.close()


def test_claude_model_discovery_is_paginated_and_deduplicated():
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.path == '/v1/models'
        assert request.headers['x-api-key'] == 'secret'
        if len(requests) == 1:
            assert request.url.params['limit'] == '1000'
            return httpx.Response(200, json={'data':[{'id':'b','display_name':'Beta'}],
                                            'has_more':True,'last_id':'b'})
        assert request.url.params['after_id'] == 'b'
        return httpx.Response(200, json={'data':[{'id':'a','display_name':'Alpha'},{'id':'b','display_name':'Beta'}],
                                        'has_more':False})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        models = LLMClient(client).list_models(LLMSettings(api_key='secret'))
    assert models == [{'id':'a','name':'Alpha'},{'id':'b','name':'Beta'}]
    assert len(requests) == 2


def test_compatible_model_discovery_works_without_key_model_or_enabled():
    def respond(request):
        assert request.url.path == '/v1/models'
        assert 'Authorization' not in request.headers
        assert not request.url.query
        return httpx.Response(200,json={'data':[{'id':'local-model'}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert LLMClient(client).list_models(LLMSettings(provider='compatible')) == [{'id':'local-model','name':'local-model'}]


@pytest.mark.parametrize('body', [{'data':[{'id':12}]}, {'data':[{'id':'ok','display_name':12}]},
                                 {'data':[],'has_more':True}, {'invalid':'secret'}])
def test_model_discovery_rejects_malformed_responses_without_leaking_secrets(body):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=body))) as client:
        with pytest.raises(LLMError) as error:
            LLMClient(client).list_models(LLMSettings(api_key='secret'))
        assert 'secret' not in str(error.value)


def test_model_discovery_rejects_repeating_cursor():
    body = {'data':[{'id':'b'}], 'has_more':True, 'last_id':'b'}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=body))) as client:
        with pytest.raises(LLMError):
            LLMClient(client).list_models(LLMSettings(api_key='secret'))


def test_saved_credentials_do_not_follow_provider_or_endpoint_changes(tmp_path):
    settings = store(tmp_path)
    settings.update(LLMSettingsPatch(base_url='https://api.anthropic.com/v1/'))
    assert settings.get().api_key == 'secret'
    settings.update(LLMSettingsPatch(provider='compatible', base_url='https://api.openai.com/v1'))
    assert not settings.get().api_key
    settings.update(LLMSettingsPatch(api_key='openai-secret'))
    settings.update(LLMSettingsPatch(base_url='http://localhost:11434/v1', api_key=''))
    assert not settings.get().api_key
    settings.update(LLMSettingsPatch(base_url='https://api.openai.com/v1', api_key='replacement'))
    assert settings.get().api_key == 'replacement'
