# MCP seats

An MCP client can play a Multiplayer bot seat. Configure its connection once
in **Settings → MCP connection**, then select a different seat for each game.
The MCP adapter uses stdio and does not require a network listener of its own.

## Setup

Install the optional adapter SDK on the machine running the MCP client:

```sh
backend/venv/bin/python -m pip install -r backend/requirements-mcp.txt
```

In Settings, generate a server token and copy the displayed Claude or Codex
command into a terminal on the backend machine. The command configures the
client's stdio adapter, backend URL and server token. Restart the client after
registering it. For a different machine, install the adapter there and adapt
its Python, PYTHONPATH and backend URL. Commands contain the server token;
protect the client configuration and avoid sharing commands. Use “Show setup
commands” to retrieve them again without rotating the token. Generate a new
server token to revoke old connections, then reconfigure each client.

The backend stores the server token in `DATA_DIR/mcp_server_token` (ignored by
Git by default) using an atomic file with mode 0600 on POSIX. This is a local
file, not an OS keychain. Treat the data directory and client configurations as
credentials, especially when relocating `MTG_DATA_DIR`. The application has
no general authentication, so its settings and credential generation endpoint
are reachable by anyone who can access it. Keep the backend on localhost unless
the LAN is trusted; see OPERATIONS.md.

## Play

1. The host adds an **MCP-Client** bot in Multiplayer and chooses its deck.
2. The host clicks the seat's 🔑 and gives the copied `bot seat <token>` to
   Codex or Claude. The token is unique to that seat and expires with it. It is
   absent from lobby snapshots and broadcasts.
3. The client calls `select_seat` with the token. The successful call connects
   the seat and makes it ready once its deck is set. A client can select a new
   seat without re-registering the MCP server.
4. The model calls `get_state` or `wait_for_turn`, then `submit_action` with an
   offered index, parameters when needed, and preferably `expected_type`. It
   may also call `set_name`, `get_decklist` and `concede`. The engine checks
   legality and returns only the selected seat's perspective.

A client silent for `MCP_SEAT_STALE_SECONDS` (default 120) is replaced by Smart
Bot until its next call. An invalid or revoked server token or seat token is
rejected. Rotating the server token invalidates existing adapters immediately.

ChatGPT can connect a local stdio adapter through a Secure MCP Tunnel; it needs
its own OpenAI tunnel configuration. A bare localhost URL cannot connect the
ChatGPT service to this stdio adapter.

Run the adapter and multiplayer checks with:

```sh
cd backend
venv/bin/python -m pytest tests/test_mcp_adapter.py tests/test_mcp_stdio.py tests/api/test_api_multiplayer.py -q
```
