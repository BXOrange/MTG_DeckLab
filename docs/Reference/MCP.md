# MCP seat (PLR-16)

An external MCP client (e.g. Claude) can play one table seat instead of the
server-side LLM `AIBot`. MCP seats are available in Multiplayer, not Solo
(which has no host-issued seat tokens). No engine change: the seat is a bot seat
(`Seat.bot_kind = "mcp"`) whose actions arrive over a token API.

## Flow

1. Host adds a bot of kind **MCP-Client** in the lobby. The seat is not ready.
2. Host picks the seat's deck and clicks 🔑: the UI fetches the seat token
   (`POST /api/multiplayer/games/{id}/bots/token`, host only), copies a
   `claude mcp add ... -e MTG_SEAT_TOKEN=...` command and shows it. The host
   pastes it into the client by hand. The token is never in a lobby
   snapshot, broadcast or `Seat.to_dict()`, and is never sent to a client over
   MCP. It dies with the seat.
3. The adapter's first call (`/api/mcp-seat/view`) marks the seat connected;
   with a deck it now counts as ready (`Seat.is_ready`).
4. A client silent for `MCP_SEAT_STALE_SECONDS` (config, default 120) is
   replaced by Smart Bot in `bots_for_game`; its next call takes the seat back.
   Configure this via `multiplayer.mcp_seat_stale_seconds` in `config.json` or
   `MTG_MCP_SEAT_STALE` in the environment.

## API (`api/mcp_seat.py`, `Authorization: Bearer <token>`)

`GET /view`, `GET /wait?timeout=` (long poll, capped by `MCP_WAIT_MAX_SECONDS`;
"something to do" = non-empty `legal_actions`, as in the bot driver),
`POST /action`, `POST /concede`, `POST /name` (display name, setup only, max `MCP_SEAT_NAME_MAX_LENGTH`), `GET /deck` (the seat's own saved decklist, i.e. before any shuffle; a player knows their own list). Actions run through `GameSession.apply_action`
with the seat as actor, so priority and timing are enforced like for humans;
views are perspective-redacted (RULE 400.2).

## Adapter (`backend/mtg_mcp/`)

Stdlib HTTP client plus FastMCP stdio server (`pip install -r
backend/requirements-mcp.txt`, optional; the app does not need it). Run from
`backend/`: `python -m mtg_mcp` with `MTG_SEAT_TOKEN` and `MTG_BASE_URL`. One
adapter serves one seat. Starting without a token exits with a clear error;
the host must configure it before launch, rather than passing credentials
through an MCP tool. Tools: `get_state`, `wait_for_turn`, `submit_action`
(index into the listed legal actions, optional `params`, optional `expected_type` guard;
`attack` offers are translated to attacker declarations), `set_name`, `get_decklist`, `concede`.

The app has no auth: the token is the only credential, so keep the server on
localhost unless the LAN is trusted (see OPERATIONS.md).

## Installation and launch

The SDK is optional for the application; only the stdio adapter needs it:

```sh
backend/venv/bin/python -m pip install -r backend/requirements-mcp.txt
```

The host's 🔑 command includes the Python interpreter, backend URL and
`PYTHONPATH`, so the adapter can launch from any working directory. This
command assumes the MCP client runs on the backend machine. For a client on
another machine, install `backend/mtg_mcp` and the optional requirements there,
use that machine's Python/module path and point `MTG_BASE_URL` at the backend.
The host supplies `MTG_SEAT_TOKEN` by hand in the MCP client's environment.

The adapter accepts MCP SDK 1.x (`FastMCP`) and 2.x (`MCPServer`); the stdio
integration was verified with SDK 2.3.0. No public tunnel or LAN listener is
required for a local client.

## Playing and validation

Read `get_state` or `wait_for_turn`, then submit an offered action by its index.
Use `expected_type` to detect a changed action type at that index. Targeted
spells/abilities require the selected targets in `params`, and an attacker with
multiple legal defenders requires `params.defender`. A single defender is
filled automatically; the adapter translates `attack` to `declare_attackers`.
The server remains responsible for all legality and actor checks.

`tests/test_mcp_stdio.py` uses a real SDK client, adapter subprocess and isolated
local HTTP server. It verifies all six tools, setup/name/decklist, perspective
redaction, normal actions and a complete shortened match ending in combat
victory. It skips when the optional SDK is absent. Run it with:

```sh
cd backend
venv/bin/python -m pytest tests/test_mcp_adapter.py tests/test_mcp_stdio.py tests/api/test_api_multiplayer.py -q
```

Chromium verification covers the waiting/connected seat row, deck/client ready
gating and host-only key/start command, including an unavailable clipboard.
