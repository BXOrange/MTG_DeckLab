"""Settings redaction and ANA-1 saved-deck analysis end to end, without paid calls."""
import pytest
from fastapi.testclient import TestClient
from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_deck_database, get_lazy_card_loader
from mtg_analyzer.services.llm_settings import default_llm_settings, LLMSettingsStore
from mtg_analyzer.services.narrative_analysis import default_narrative_analysis, NarrativeAnalysis, AnalysisDatabase
from mtg_analyzer.services.deck_database import DeckDatabase
from tests.api.test_api_saved_decks import _FakeLoader
from tests.services.test_bots import land
from tests.services.test_llm import FakeNarrator

@pytest.fixture
def setup(tmp_path):
    database = DeckDatabase()
    settings = LLMSettingsStore(tmp_path / 'llm.json')
    client = FakeNarrator()
    analysis_db = AnalysisDatabase()
    service = NarrativeAnalysis(analysis_db, settings, client)
    overrides = {get_deck_database:lambda:database, get_lazy_card_loader:lambda:_FakeLoader({'Forest':land()}),
                 default_llm_settings:lambda:settings, default_narrative_analysis:lambda:service}
    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app), client, settings
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)
        analysis_db.close()
        database.close()

def test_configuration_is_redacted_and_connection_disabled_until_ready(setup):
    http, _, settings = setup
    assert not http.get('/api/llm/settings').json()['ready']
    assert http.post('/api/llm/test').status_code == 503
    response = http.put('/api/llm/settings', json={'enabled':True, 'model':'mock', 'api_key':'secret'})
    assert response.status_code == 200
    assert response.json()['ready']
    assert response.json()['api_key_configured']
    assert 'secret' not in response.text
    assert http.put('/api/llm/settings', json={'base_url':'file:///tmp/key'}).status_code == 422
    assert settings.get().api_key == 'secret'
    http.put('/api/llm/settings', json={'api_key':''})
    assert settings.get().api_key == 'secret'
    http.put('/api/llm/settings', json={'clear_api_key':True})
    assert not http.get('/api/llm/settings').json()['ready']

def test_analysis_link_cache_force_language_and_edit_invalidation(setup):
    http, narrator, _ = setup
    http.put('/api/llm/settings', json={'enabled':True,'model':'mock','api_key':'secret'})
    deck = http.post('/api/decks/save',json={'name':'Green','mainboardText':'2 Forest'}).json()
    url = '/api/decks/' + deck['id']
    assert http.get(url+'/analysis').status_code == 404
    response = http.post(url+'/analyze',json={'language':'en'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['result']['cohesion_score'] == 70
    assert not result['cached']
    assert narrator.calls[0]['cards'][0]['quantity'] == 2
    assert narrator.calls[0]['language'] == 'en'
    assert http.get(url).json()['analysisId'] == result['id']
    assert http.get(url+'/analysis').json()['id'] == result['id']
    assert http.post(url+'/analyze',json={'language':'en'}).json()['cached']
    assert len(narrator.calls) == 1
    assert not http.post(url+'/analyze',json={'language':'en','force':True}).json()['cached']
    http.post('/api/decks/save',json={'id':deck['id'],'name':'Renamed','mainboardText':'2 Forest'})
    assert http.get(url+'/analysis').status_code == 200
    http.post('/api/decks/save',json={'id':deck['id'],'name':'Renamed','mainboardText':'3 Forest'})
    assert http.get(url+'/analysis').status_code == 404
    assert not http.post(url+'/analyze',json={'language':'en'}).json()['cached']
    assert len(narrator.calls) == 3

def test_missing_deck_and_unresolved_cards_do_not_call_provider(setup):
    http, narrator, _ = setup
    assert http.post('/api/decks/missing/analyze').status_code == 404
    deck = http.post('/api/decks/save',json={'name':'Unknown','mainboardText':'1 Unknown Card'}).json()
    assert http.post('/api/decks/'+deck['id']+'/analyze').status_code == 422
    assert not narrator.calls

def test_invalid_environment_is_reported_without_secret(setup, monkeypatch):
    http, _, _ = setup
    monkeypatch.setenv('MTG_LLM_TIMEOUT_SECONDS','secret-invalid')
    response = http.get('/api/llm/settings')
    assert response.status_code == 503
    assert 'secret-invalid' not in response.text


def test_model_discovery_previews_unsaved_configuration_without_persisting_or_reusing_other_provider_key(setup, monkeypatch):
    from mtg_analyzer.api import llm
    from mtg_analyzer.services.llm_settings import LLMSettingsPatch
    http, _, settings = setup
    settings.update(LLMSettingsPatch(api_key='saved-secret'))
    seen = []
    class ModelClient:
        def list_models(self, config):
            seen.append(config)
            return [{'id':'model-a','name':'Model A'}]
    monkeypatch.setattr(llm, 'LLMClient', ModelClient)
    result = http.post('/api/llm/models',json={})
    assert result.status_code == 200
    assert 'saved-secret' not in result.text
    assert seen[-1].api_key == 'saved-secret'
    result = http.post('/api/llm/models',json={'provider':'compatible','base_url':'https://api.openai.com/v1'})
    assert result.status_code == 200
    assert not seen[-1].api_key
    assert settings.get().provider == 'anthropic'
    http.post('/api/llm/models',json={'provider':'compatible','base_url':'https://api.openai.com/v1','api_key':'preview-secret'})
    assert seen[-1].api_key == 'preview-secret'
    assert settings.get().api_key == 'saved-secret'
    http.post('/api/llm/models',json={'clear_api_key':True})
    assert not seen[-1].api_key
    assert settings.get().api_key == 'saved-secret'
    http.post('/api/llm/models',json={'base_url':'https://elsewhere.test/v1'})
    assert not seen[-1].api_key
    assert http.post('/api/llm/models',json={'base_url':'file:///tmp/key'}).status_code == 422


def test_model_discovery_provider_failure_is_sanitized(setup, monkeypatch):
    from mtg_analyzer.api import llm
    from mtg_analyzer.services.llm_client import LLMError
    http, _, _ = setup
    class ModelClient:
        def list_models(self, config):
            raise LLMError('LLM model list returned HTTP 401')
    monkeypatch.setattr(llm, 'LLMClient', ModelClient)
    response = http.post('/api/llm/models',json={})
    assert response.status_code == 503
    assert response.json()['detail'] == 'LLM model list returned HTTP 401'
