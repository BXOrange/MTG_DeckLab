"""Server-wide LLM configuration; API responses never include credentials."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from mtg_analyzer import config


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    provider: Literal['anthropic', 'compatible'] = 'anthropic'
    base_url: str = 'https://api.anthropic.com/v1'
    model: str = ''
    api_key: str = Field(default='', repr=False, exclude=True)
    timeout_seconds: float = Field(default=15, ge=1, le=30)
    max_tokens: int = Field(default=2048, ge=128, le=8192)
    bot_calls_per_turn: int = Field(default=8, ge=1, le=32)

    @field_validator('base_url')
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip('/')
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use an HTTP(S) API base URL without credentials, query or fragment')
        return value

    @field_validator('model', 'api_key')
    @classmethod
    def trim(cls, value):
        return value.strip()

    @property
    def ready(self):
        return self.enabled and bool(self.model) and (self.provider == 'compatible' or bool(self.api_key))

    def public(self):
        return self.model_dump() | {'api_key_configured': bool(self.api_key), 'ready': self.ready}

    def identity(self):
        # Credentials never enter prompts, cache keys or game state.
        return {'provider': self.provider, 'base_url': self.base_url, 'model': self.model}


class LLMSettingsPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool | None = None
    provider: Literal['anthropic', 'compatible'] | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    clear_api_key: bool = False
    timeout_seconds: float | None = Field(default=None, ge=1, le=30)
    max_tokens: int | None = Field(default=None, ge=128, le=8192)
    bot_calls_per_turn: int | None = Field(default=None, ge=1, le=32)


class LLMSettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else config.DATA_DIR / 'llm_settings.json'
        self._lock = threading.RLock()

    def _stored(self):
        defaults = dict(config._FILE_CONFIG.get('llm', {}))
        defaults = {k: v for k, v in defaults.items() if not k.startswith('_')}
        if self.path.exists():
            try:
                defaults.update(json.loads(self.path.read_text()))
            except (ValueError, OSError):
                pass
        return defaults

    def get(self):
        with self._lock:
            values = self._stored()
            for field in LLMSettings.model_fields:
                env = os.environ.get('MTG_LLM_' + field.upper())
                if env is not None:
                    values[field] = env
            return LLMSettings.model_validate(values)

    def update(self, patch: LLMSettingsPatch):
        with self._lock:
            values = self._stored()
            previous = LLMSettings.model_validate(values)
            changes = patch.model_dump(exclude_none=True, exclude={'clear_api_key'})
            if not (changes.get('api_key') or '').strip():
                changes.pop('api_key', None)  # blank UI field means preserve
            values.update(changes)
            if patch.clear_api_key:
                values['api_key'] = ''
            settings = LLMSettings.model_validate(values)
            if 'api_key' not in changes and (settings.provider, settings.base_url) != (previous.provider, previous.base_url):
                settings.api_key = ''
            values = settings.model_dump() | {'api_key': settings.api_key}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.llm-')
            try:
                with os.fdopen(fd, 'w') as handle:
                    json.dump(values, handle)
                os.replace(name, self.path)  # mkstemp keeps key file mode 0600
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            return self.get()


@lru_cache(maxsize=1)
def default_llm_settings():
    return LLMSettingsStore()
