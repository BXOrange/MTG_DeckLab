# LLM integration: AI Bot and ANA-1

The optional server-wide LLM serves two independent uses: the `ai` seat policy
and narrative analysis of saved decks. Deterministic policies remain available.

## Configuration

In the separate **Settings → LLM** card (beside general settings on wide screens,
below them on narrow screens), enable the integration, choose Claude/Anthropic or a
Chat Completions compatible server, enter its API base URL and API key when
required, then choose a model from the automatically loaded dropdown. Model
discovery also works before saving/enabling the integration. Provider, URL and
key changes refresh the list; a reload button is available. Loading failures or
servers without a model-list API allow manual model-ID entry. Saved IDs remain
selectable even if absent from the current list. Save before testing the
connection; model listings alone do not establish Chat Completions/JSON support.
A compatible local endpoint may work without a key.
Switching providers in Settings fills `https://api.anthropic.com/v1` for
Claude or `https://api.openai.com/v1` for the compatible provider; the field
remains editable for local/custom endpoints. Loading saved settings preserves
the saved URL. The base URL includes the API version prefix, e.g. `https://api.anthropic.com/v1`.
The transport appends `/messages` or `/chat/completions` respectively.

Settings are server-wide, including for other connected players. Playing an
AI seat sends that seat's own deck list, offered actions and perspective-redacted
state to the configured provider. Narrative analysis sends the saved deck's
sections and resolved Oracle text. The connection test also issues a provider
request. Provider usage may incur charges.

Configuration precedence is `MTG_LLM_<FIELD>` environment variables →
`DATA_DIR/llm_settings.json` → the `llm` section of `config.json` → defaults.
Fields are `enabled`, `provider` (`anthropic`/`compatible`), `base_url`, `model`,
`api_key`, `timeout_seconds` (1–30, default 15), `max_tokens` (128–8192, default
2048) and `bot_calls_per_turn` (1–32, default 8). UI exposes all except token
limit. Keep keys out of committed configuration. Runtime settings are written
atomically with mode 0600; API responses return only `api_key_configured`,
never the key. An empty key field preserves it for the same endpoint;
changing provider/URL clears a stored key unless a new one is supplied; explicit clear removes the
stored key. Environment overrides continue to apply after saving/clearing.

- `GET /api/llm/settings`: public settings and `ready`.
- `PUT /api/llm/settings`: partial update; `clear_api_key` explicitly clears.
- `POST /api/llm/models`: unsaved settings preview → available `{id,name}` models;
  no settings are persisted. Stored keys are used only for the same provider/URL.
  Calls the provider's `/models`, following Claude cursors with bounded pagination.
- `POST /api/llm/test`: explicit structured connection test.

HTTP 429 errors distinguish known API quota/billing codes from other usage or
rate limits and show a numeric `Retry-After` delay when supplied. Raw provider
messages are never exposed. Requests are not automatically retried; quota
errors require checking the provider account's API billing and usage limits.

## Policies and gameplay

Individual policies live in `services/bot_policies/{base,goldfish,greedy,
smart,mana_maximizer,ai}.py`; `services/bots.py` owns the registry/driver and
reexports the classes for existing callers. `Bot.prepare(session)` attaches
policy context before each fresh client view. AI and Smart retain per-session
memory when lobby policy instances are rebuilt.

`AIBot` uses Smart Bot's detected archetype, identity, commander themes and
local Spellbook matches as prompt context. It chooses an offered index and
optional parameters (targets, X, attackers, defenders, blockers, card name).
Typed output and offered-parameter checks precede ordinary engine validation.
It cannot mutate game state or bypass rules. Omitted parameters use deterministic
completion. This helps assemble included win conditions; it is not an exhaustive
combo solver and inherits the engine's supported card behavior.

Two worker threads, at most four queued/running jobs, a bounded prompt and a
per-seat/per-turn call budget limit work. Workers receive copied redacted data,
not the engine/session. While a request is pending the driver preserves priority.
The next driver invocation collects the result; a changed position discards it.
Solo polls its view while `bot_status` reports `thinking`; the multiplayer
watchdog continues processing jobs without blocking on provider I/O. Restart
cancels queued requests and clears policy memory. Already-running requests may
finish but their old results are ignored. Setup/forced passes stay deterministic.
Missing settings, timeouts, invalid results, exhausted budgets or worker capacity
fall back to Smart Bot, with a public status. Failed positions are not retried
on every tick. No actual paid-provider calls are needed for the test suite.

## ANA-1 saved-deck analysis

`POST /api/decks/{id}/analyze` accepts optional
`{"language":"de","force":false}` (`en` also supported). It resolves the saved
commander/mainboard/sideboard, builds identity and included combo context, and
requests a validated `NarrativeResult`: summary, archetype, win conditions,
synergies, cohesion score (0–100), issues and recommendations. Claude output
uses a forced tool call with the JSON schema; compatible providers use JSON
response mode plus schema instructions. Malformed results are not persisted.
Provider failures return sanitized HTTP 503; deck/card problems return 404/422.

Results live in persistent `DATA_DIR/analyses.db`, separate from card caches.
The fingerprint covers deck input/Oracle context, language, prompt version and
provider endpoint/model. Concurrent identical requests share the persisted
result. `force:true` replaces that fingerprint's result. Responses carry `id`,
`deck_id`, timestamp, prompt version, provider identity, `result` and `cached`.
`Deck.analysis_id` links the current saved deck to the result;
`GET /api/decks/{id}/analysis` retrieves it. Deck-section or selected-archetype
edits clear the link; cosmetic renaming preserves it. A provider request that
finishes after the deck was edited does not overwrite the new deck's link.

ANA-1 is the backend contract. Narrative presentation (ANA-2) and the UI cache-age
indicator (ANA-3) remain separate work; existing static analysis is unchanged.

## Primary provider references

- [Claude Messages API](https://platform.claude.com/docs/en/api/messages/create):
  request format, system prompt, tool schema and forced tool selection.
- [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs):
  schema-based output contracts. Local Pydantic validation is always enforced.
- [Magic bot research and Smart Bot design](SMART_BOT.md).

Model discovery follows the official [OpenAI Models API](https://developers.openai.com/api/reference/resources/models/methods/list)
and [Claude Models API](https://platform.claude.com/docs/en/api/models/list).
