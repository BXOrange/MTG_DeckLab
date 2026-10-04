"""Local server-wide LLM settings and explicit connection test."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from mtg_analyzer.services.llm_settings import LLMSettings, LLMSettingsPatch, default_llm_settings
from mtg_analyzer.services.llm_client import LLMClient, LLMError

router = APIRouter(prefix='/api/llm', tags=['llm'])


@router.get('/settings')
def settings(store=Depends(default_llm_settings)):
    try:
        return store.get().public()
    except (ValidationError, OSError):
        raise HTTPException(503, 'Invalid server LLM settings') from None


@router.put('/settings')
def save_settings(patch: LLMSettingsPatch, store=Depends(default_llm_settings)):
    try:
        return store.update(patch).public()
    except ValidationError:
        raise HTTPException(422, 'Invalid LLM settings') from None
    except OSError:
        raise HTTPException(503, 'LLM settings could not be saved') from None


class ConnectionResult(BaseModel):
    connected: bool


@router.post('/test')
def test_connection(store=Depends(default_llm_settings)):
    try:
        result = LLMClient().generate(store.get(), 'Connection test. Set connected to true.', {}, ConnectionResult)
        if not result.connected:
            raise LLMError('LLM connection test did not succeed')
        return {'connected': True}
    except (ValidationError, OSError):
        raise HTTPException(503, 'Invalid server LLM settings') from None
    except LLMError as exc:
        raise HTTPException(503, str(exc)) from None


@router.post('/models')
def models(patch: LLMSettingsPatch = LLMSettingsPatch(), store=Depends(default_llm_settings)):
    """Preview the form's model list without persisting settings/credentials."""
    try:
        saved = store.get()
        values = saved.model_dump() | {'api_key': saved.api_key}
        changes = patch.model_dump(exclude_none=True, exclude={'clear_api_key'})
        key = changes.pop('api_key', None)
        values.update(changes)
        preview = LLMSettings.model_validate(values)
        # Never forward a saved key to a different provider/endpoint.
        if patch.clear_api_key:
            preview.api_key = ''
        elif key and key.strip():
            preview.api_key = key.strip()
        elif (preview.provider, preview.base_url) != (saved.provider, saved.base_url):
            preview.api_key = ''
        return {'models': LLMClient().list_models(preview)}
    except (ValidationError, OSError):
        raise HTTPException(422, 'Invalid LLM settings') from None
    except LLMError as exc:
        raise HTTPException(503, str(exc)) from None
