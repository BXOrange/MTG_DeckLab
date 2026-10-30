# Backlog — open work, as tickets

**The single list of open work, backend and frontend.** Put a new line in the right document:

| Kind | Lives in | Rule |
| --- | --- | --- |
| **Open points** | this file | Only open scope. No history, no residue. |
| **Worklogs** | [Done_Backend.md](Done_Backend.md), [Done_Frontend.md](Done_Frontend.md) | What shipped and *why it was built that way*. |
| **Examples** | [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) | Calibration samples + strategy for the parser tail. |
| **Singleton queue** | [singletons.md](singletons.md) | One-off cards (confirmed via `parser_probe.py blocked` to share no cluster) — a queue for `hand-author-card`, never batched into a ticket; promote a pair that shares a shape. |
| **Working memory** | [workingOn.md](workingOn.md) | Resumable state of the ticket in progress, incl. a partly done ticket's **residue**. Read first when resuming; delete the block on close. |

**Closing a ticket = deleting it here** and filing its narrative in the matching `Done_*.md`
section — no `[x]`, "shipped" note or "moved to Done" pointer. A partly done ticket keeps only its
terse open point (id, title, one clause) here; residue goes in its `workingOn.md` block. Ticket ids
are stable; reuse a retired id only for the same subject. Sequencing:
[10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md). Parked tickets and permanent non-goals live in
[DEFERRED.md](DEFERRED.md) (promote by moving the block back here).

| Prefix | Category |
| --- | --- |
| `ENG` | Game engine — turn/stack/priority loop, layers, targeting, combat plumbing |
| `PAR` | Parser — oracle-text → `AbilitySpec` recognition (`parser/oracle/`) |
| `MEC` | Game mechanics — a named MTG mechanic with no engine primitive yet |
| `PLR` | Player management — seats, multiplayer, bots, accounts, sessions |
| `VIS` | Visuals — frontend UI/UX |
| `DB` | Database — card cache, saved decks, persistence, data freshness |
| `ANA` | Deck analysis — UC2 (LLM + presentation) |
| `BUG` | Bugs — a shipped behaviour that is wrong (a wrong-but-`MODELED` claim, a silently dropped clause); not missing coverage |

---

## ENG — Game engine

-No Tickets-

## PAR — Parser

Fragment-axis tickets (PAR-220…224), from the v792 scan (9,179 open Commander cards, 13,440 open
sentences; the best exact template unlocks 5 cards, so each ticket is a shared grammar axis over
the PAR-210 object phrase, not template rows). Counts are `touched` / `only` (open cards with the
axis / cards whose every open sentence has it; an overlapping upper bound). Each ticket re-scans
with `find-fragments` before and after, diffs full-pool specs for zero losses and executes newly
claimed cards.

## MEC — Game mechanic

-No Tickets-

## PLR — Player management

- **PLR-9 · User accounts.** Login/signup (docs/04 PART 4), auth token
  storage + attachment to API/WebSocket calls, browser-refresh reconnect
  flow (docs/04 S1), and login/signup pages. Saved decks are unscoped until
  this exists — anyone hitting the API sees every deck. Also what actually
  closes the collision gap the PLR-4 client-token stub (`services/
  lobby.py`'s `client_token`, `Done_Backend.md` "Client-token identity
  stub") only covers halfway: that token is unsigned, client-trusted data —
  copy/clear/forge it and nothing notices — and a client that has never
  opened Profil still resolves purely by name, the original "two people
  sharing a name share a seat" collision. Fine for a LAN table, not for
  anything public. Builds on the per-player secret from BUG-39 (session cookie
  `HttpOnly`, `SameSite=Strict`). The 2026-10-30 audit also requires scoping
  saved decks per account (today `DELETE /api/saved-decks/{id}` deletes anyone's
  deck) and dropping the legacy name fallback in `Lobby.connect` (taking over a seat
  by name alone).
- **PLR-16 · Bind player assets to an owner instead of the free-text name.** Sleeves,
  token art and favorites (`services/player_assets.py`) are keyed by the freely chosen
  name: anyone can upload or delete under any name (`/api/players/{name}/…`). The sweeper
  also deletes a name's uploads when a foreign token expires (`delete_all_for_player(name)`
  in `api/multiplayer_ws.sweep_once`), which lets an attacker who uses the victim's name with
  their own token wipe the victim's art. Tasks: until PLR-9 lands, accept writes/deletes only
  with the BUG-39 secret of the owning player; purge only uploads the expired token created
  itself (store the token/owner per row); after PLR-9, migrate to `account_id`.
- **PLR-17 · Protect admin/server routes.** Anyone who can reach the port can change or clear
  the LLM settings (`PUT /api/llm/settings`), burn LLM quota (`/api/llm/test`, narrative
  analysis, LLM bots) and start the card-pool/combo updates (`/api/cards/update`,
  `/api/combos/update`). Tasks: allow these routes only from loopback, or with an admin token
  following the `console_status.py` pattern (`MTG_CONSOLE_TOKEN`); hide or disable them in the
  frontend for LAN clients; tests.

## VIS — Visuals

- **VIS-15 · Deck building tool.** Add a dedicated navigation section for creating and editing
  Commander decks with card search/filtering, commander selection, card quantities, live deck
  metrics, server-authoritative legality feedback and saved drafts/decks for analysis and play;
  scope and acceptance criteria: [project goal](../requirements/02_MVP_USECASES_REVISED.md#deck-building-tool).
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9 (Space/Enter/E for pass and yield already exist).
- **VIS-9 · Accessibility** — alt-text on cards, tab navigation,
  high-contrast mode. docs/05 PART 10.
- **VIS-10 · Responsive/mobile layout** — only checked at desktop width.

## DB — Database

> **Gotcha:** adding a field to `Card` changes the schema hash, and
> `CardDatabase` wipes the whole app cache on mismatch. Recover offline with
> `python scripts/import_bulk.py --reseed-only` (rebuilds ~34k rows from
> `RawCardStore`). A targeted per-field backfill is never the right answer —
> the wipe is all-or-nothing.

## ANA — Deck analysis

- **ANA-2 · Narrative analysis UI** — win conditions, archetype, synergies,
  cohesion score, issues. Sits alongside the existing static/Bracket
  sub-tabs, not replacing them. ANA-1 backend contract is available (see
  [LLM integration](../Reference/LLM_INTEGRATION.md)).
- **ANA-3 · Cache indicator** ("Analysis from X ago") for that LLM result.
  The backend provides `created_at` and `cached`.

## BUG — Bugs

Security audit 2026-10-30 (BUG-38…45). A1/A2 reproduced against the running app via the API.
Order: BUG-38 → BUG-39 → BUG-40/41/42 (one shared middleware) → BUG-43…45.

- **BUG-38 · Multiplayer sessions reachable through the solo/goldfish APIs (critical).** The
  table's `session_id` is public in the lobby snapshot (`LobbyGame.to_dict`) and
  `GameSessionManager.get` ignores the mode, so anyone can read every hand
  (`GET /api/game/{sid}`, `view()` without `perspective`), the full state including library
  order (`/replay-export`), act as the active player (`/action`, `actor_id=None`), and
  `/rewind` (bypassing the takeback limit), `/restart` or `DELETE` the table; `/ws/game/{sid}`
  does the same and broadcasts the unredacted view.
  Tasks: mode check in `api/game.py`/`api/solo.py` `_session()` (MULTIPLAYER only through
  `api/multiplayer.py`; solo only through `api/solo.py`); remove `/ws/game` (`api/game_ws.py`
  together with the unimported `frontend/src/js/gameSocket.js`; also update `console_status.py`'s
  `game_connections`) or bind it to a seat and perspective;
  check whether `session_id` must appear in `LobbyGame.to_dict` at all; regression tests per
  route (MP session → 404/403, no `hand` leak).
- **BUG-39 · Impersonation through the public `player_id` (critical).** Every lobby/seat ID
  (`LobbyPlayer.to_dict`, `Seat.to_dict`, `host_id`) reaches every client, and every REST/WS
  route trusts the `player_id` from the request: read a foreign hand
  (`GET /api/multiplayer/games/{gid}?player_id=`), act/concede/take back/use host options in
  someone else's name; `connect` with a foreign `playerId` plus your own `clientToken` binds that
  token to the victim, renames them and kicks their socket (`replaced`).
  Tasks: generate a secret server-side per `LobbyPlayer` (`secrets.token_urlsafe`), deliver it
  only in `welcome`/`connect`, never in snapshots; check it in every mutating multiplayer route,
  in `game_view`, `ui-draft` and the WS (`api/multiplayer_ws.py`), with `compare_digest`;
  reclaim through `player_id` only together with the secret; adapt the frontend
  (`lobbySocket.js`, `multiplayerView.js`, `api.js`); tests: foreign ID without the secret →
  403, hijack via `connect` no longer possible. Prerequisite for PLR-9.
- **BUG-40 · No Origin check on WebSockets (CSWSH).** CORS does not apply to WS; any website
  the user opens can open `ws://localhost:8000/ws/lobby` (and `/ws/game`) and act together with
  BUG-38/39. Tasks: check `Origin` in the handshake against `_LOCAL_DEV_ORIGIN_REGEX` plus the
  server's own host (and the `--host` address), otherwise close 1008; test with a foreign Origin.
- **BUG-41 · No Host-header check (DNS rebinding).** `Host: attacker.example` is accepted, so
  a website can reach the whole API on 127.0.0.1 through rebinding (read/delete decks, LLM
  settings, uploads, start jobs). Tasks: `TrustedHostMiddleware` in `api/app.py` with
  `localhost`/`127.0.0.1` plus the `--host` address/LAN IP from `setup/start.py` (pass it
  through `config`); test with a foreign Host → 400; update OPERATIONS.md.
- **BUG-42 · CSRF through simple requests.** JSON bodies are protected (FastAPI rejects
  `text/plain`), but without a preflight cross-origin requests get through: multipart uploads
  (`/api/players/{name}/token-images`, `/sleeves`) and POSTs without a body
  (`/api/cards/update` starts the Scryfall download, `/api/combos/update`, `/api/llm/test`
  costs an LLM call, `/api/game/{id}/restart`). Tasks: middleware that rejects unsafe methods
  with a foreign/missing `Origin` (or a required custom header that forces a preflight; send it
  in `api.js`); shares the allowlist with BUG-40/41; tests per route class.
- **BUG-43 · No resource limits (DoS).** `GameSessionManager` has no cap or expiry (every
  goldfish/solo/replay start stays in RAM along with its undo history); unlimited lobby
  players/tables; unlimited uploads per name (5 MB each, read completely before the size check);
  unlimited bug-report files. Tasks: session TTL + LRU cap (named config constants) and sweeping
  in the existing `sweeper`; caps on players/tables in `Lobby`; per-name quota in
  `PlayerAssetStore`; read uploads in chunks and abort at the limit; cap/rotate
  `BUG_REPORT_DIR`; tests.
- **BUG-44 · Upload and HTTP hardening.** The uploaded content type comes from the client and
  is served back unchecked; there are no security headers at all. Tasks: check magic bytes
  against the declared type (PNG/JPEG/WebP/GIF) in `api/player_assets.py`; middleware with
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options`/`frame-ancestors`
  and a CSP that fits the buildless frontend (check inline styles/scripts first); tests.
- **BUG-45 · Minor audit findings.** (a) LLM `base_url` is freely settable → blind SSRF against
  internal hosts (`/api/llm/models`, `/test`): allow private/link-local addresses only for
  `provider=compatible` and only after an explicit opt-in, or resolve and check the IP;
  (b) `requirements.txt` has no pins/lockfile → pin with hashes (keep it consistent with the
  offline wheels in `setup/wheels/`); (c) a bug report with the `session_id` of a multiplayer
  table stores every hidden zone; acceptable locally, but after BUG-39 only accept it from a seat
  of that table.
