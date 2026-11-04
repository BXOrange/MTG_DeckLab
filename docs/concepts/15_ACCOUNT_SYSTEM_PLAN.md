# Account system, run modes and administration — plan for PLR-9

Implementation plan; **nothing here is delivered yet**. The current behaviour (loopback by
default, `--host` for LAN, no authentication) stays authoritative in
[OPERATIONS.md](../Reference/OPERATIONS.md) and [PLAYER_PROFILE.md](../Reference/PLAYER_PROFILE.md)
until a sub-ticket lands and updates them. Tickets: [BACKLOG.md](../implementation-state/BACKLOG.md)
(`PLR-9a`–`PLR-9e`, coordinated with `PLR-16`, `PLR-17`; missing-card discovery is the separate `ANA-5`).

Items marked **[decided]** come from the product owner; **[proposal]** is a recommendation to
confirm or overrule during the sub-ticket that owns it.

## 1. Scope and decisions

Local username/password accounts, server-issued sessions, account-owned saved decks, authenticated
multiplayer reconnects, a separate administration surface. Keep the static ES-module frontend,
FastAPI and SQLite under `MTG_DATA_DIR`; no external identity service, email delivery or online
dependency at startup. **One name per account [decided]:** the account name is the only visible
name (login, lobby seat, UI); there is no separate display name. Internally every account gets an
opaque, immutable **`player_uuid`** (the `account_id`) that abstracts the name: ownership, seats,
assets, sessions, replays and logs reference the UUID, never the name, so a rename cannot change who
owns what. `Deck.author` stays descriptive credit (free text, not an identity).

- **Run modes [decided].** Three startup modes replace today's "loopback unless `--host`":

  | Mode | Start | Reachable from | Transport | Notes |
  | --- | --- | --- | --- | --- |
  | **LAN** (default) | `./start.sh` | configurable network allowlist (e.g. `192.168.179.0/24`); without configuration the subnets of the host's attached interfaces, always plus loopback — see §3 | HTTP allowed | accounts required; weaker cookie profile, see §3 |
  | **Online** | `--online` | any address | HTTPS only | `__Host-` cookies, HSTS, no IP allowlist; remote admin only with MFA |
  | **Local dev** | `--localdev` | loopback only (refuses to combine with LAN/online binds) | HTTP | enables the **default-localuser** |

- **Default-localuser [decided].** In `--localdev` a built-in player account (`local`) is signed in
  automatically for loopback requests and can play without a login. It can log out and be replaced by
  a real player login. It exists and is accepted **only** in `--localdev`; in LAN/online it is
  unreachable (cannot log in, no automatic session). The login-free path is opt-in, so every other
  mode behaves as a real multi-account server. Reserved names (`local`, `admin`, bot names) cannot be
  registered.
- **Admin surface [decided].** Admin and player identities are separate, admin is not a player
  superset (matrix in §6). The admin entrypoint is a plain **`/admin` page** on the one listener
  (e.g. `http://127.0.0.1:8765/admin`), loopback-only in every mode; remote admin exists only with
  `--online`, HTTPS and MFA. `--localdev` keeps it reachable locally. Admin has **no stored session**:
  every privileged request re-supplies the password (§6).
- **Registration by invitation [decided].** Signing up requires an **invitation token**; players
  and admins can generate them (§3 *Invitations*). There is no open registration in any mode.
  Anonymous card browsing and text-only deck parsing stay available; persistence and human
  multiplayer require a login (the default-localuser counts as a login in `--localdev`). No loopback
  bypass outside `--localdev`.
- **Unique names [decided].** The account name is unique after normalization (NFKC + case-fold,
  trimmed, bounded length) and is the multiplayer player name, so two seats can never share a name.
  Signup therefore reveals "name taken" — accepted by design; *login* failures stay generic. The
  name doubles as the login name and is visible to other players, so valid login names are known to
  anyone in a lobby: throttling and generic failures carry the protection. Names that
  collide with bot names or reserved words are refused. Enforced by a unique index (concurrent
  signup/rename tests), not by a pre-check. [proposal] renaming is allowed only while the player is in
  no lobby/game; running games, replays and bug reports keep the UUID plus the name at the time, and
  the old name stays reserved for the tombstone period (§6) against impersonation.
- **Out of scope (follow-ups):** email verification, OAuth, private-deck sharing, user data export.

## 2. Sub-ticket map

| Ticket | Delivers | Needs |
| --- | --- | --- |
| **PLR-9a** | Run modes + IP allowlist, `accounts.db`, migrations, password hashing, sessions, `/api/auth`, CSRF/Origin extension, throttling, default-localuser, invitation tokens, login/signup UI slice | — |
| **PLR-9b** | Deck scope/owner columns, authorization through every `get_deck` consumer, private game-session ownership, legacy-deck migration command | 9a |
| **PLR-9c** | Multiplayer identity bound to accounts, authenticated WS, single-session lock, removal of name/token/secret fallbacks | 9a, 9b |
| **PLR-9d** | Admin entrypoint + `/api/admin`: players (list/create/disable/enable/delete, session revoke), global-deck CRUD, allowlisted DB-update jobs, audit log | 9a, 9b (+ PLR-17 for update-route enforcement) |
| **PLR-9e** | Encryption at rest, backups/restore, secrets handling, security-event logging, OWASP test mapping, coordinated cutover and docs | 9a–9d, PLR-16 |

Release in dependency order; **ship enforcement and client updates together and never expose a
partially protected deployment [decided: by process, no feature flag]** — 9a–9d are developed and
merged on the integration branch (`feature/PLR-9`) only; nothing reaches `main`/a real install, and
the run-mode default (incl. the `CLAUDE.md`/OPERATIONS startup text) does not flip, before the 9e
cutover. Until then the current behaviour stays authoritative. The code may switch the default on the
branch; the docs and `CLAUDE.md` follow only at 9e.

Each sub-ticket ships its own frontend slice. `PLR-16` (asset ownership) is a hard gate for
the cutover; without it legacy asset mutations stay disabled. Missing-card discovery (`ANA-5`) is
independent of the cutover.

## 3. PLR-9a — Run modes, storage and authentication

**Run modes and network gate**
- Extend `request_guard.py` (BUG-40/41/42) rather than adding a second guard: add a **peer-address
  allowlist** evaluated on the ASGI client address (never `X-Forwarded-For` unless the peer is a
  configured trusted proxy). **The built-in `frontend_proxy.py` only fetches static files from the loopback-only
  frontend server (backend → frontend), so clients connect to the backend directly and the backend sees
  their real address. A *third-party* reverse proxy in front of the backend is different: a proxy
  connecting from loopback must never make a LAN client look local, which is a precondition for the
  loopback-only `/admin` gate and the `--localdev` default-localuser.** The admin and
  default-localuser gates therefore also reject requests carrying forwarding headers
  (`X-Forwarded-For`, `Forwarded`) or a non-loopback `Host`.
  **Configurable [decided]:** `MTG_ALLOWED_NETWORKS` (comma-separated CIDRs, e.g. `192.168.179.0/24`)
  plus a matching `start.py` option. When set it is the complete list (loopback is always added); when
  unset the list is loopback ∪ the subnets of the host's attached interfaces (VPN included).
  **Fail-closed:** if interface enumeration fails (small dependency such as `psutil`, or stdlib), fall
  back to loopback only and log loudly — never to a wider private range. Handle IPv6 (unmap
  `::ffff:a.b.c.d`, link-local zone IDs) and invalid CIDRs (startup error). Log the active allowlist at
  startup. Applies to HTTP and WS; evaluate together with the existing Host allowlist
  (`WILDCARD_BIND_HOSTS`). State plainly in the docs that the allowlist is a convenience boundary, not
  authentication: a shared WLAN, foreign tailnet devices or container bridges inside the allowed
  subnet are still reachable, so accounts remain mandatory.
- `config.py` exposes the mode; `setup/start.py` gains `--online` and `--localdev` (mutually
  exclusive; `--host` is superseded by the mode and kept only as a documented override).
- Update [OPERATIONS.md](../Reference/OPERATIONS.md) and the `CLAUDE.md` startup directive at the 9e
  cutover, together with the default flip for real installs. Starting stays offline-safe (no network needed at startup).
- **LAN cookie profile [proposal]:** over HTTP `__Host-` and `Secure` are impossible. LAN mode uses a
  distinct cookie name, `HttpOnly`, `SameSite=Lax`, server-side idle/absolute expiry, and relies on the
  IP allowlist; the residual risk (credentials/session readable by a passive observer on the same
  network) is documented, and `--online` is the answer for anything beyond a trusted network.
  `--online` refuses to start without TLS (own certificate or a declared TLS-terminating proxy).

**Storage**
- New **`accounts.db`** under `MTG_DATA_DIR`, separate from the deck store so credentials never share
  a file with deck data and restore boundaries are simple. Explicit, versioned, transactional,
  additive migrations (the schema-hash wipe warning is **not** a migration mechanism). Tables:
  accounts, password hashes, session-token digests, creation/expiry/revocation timestamps, name
  tombstones. Back up real databases before any conversion.

**Password hashing [proposal, decide in 9a with measurements]**
- Behind a small `PasswordHasher` interface; the stored string carries algorithm + parameters so any
  switch or parameter rise is a rehash-on-login, never a flag day.

  | Option | Dependency | Fit |
  | --- | --- | --- |
  | **Argon2id** (`argon2-cffi`) | new wheel (vendor in `setup/wheels/`) | OWASP first choice; memory-hard; baseline 19 MiB / 2 iterations / p=1 |
  | **scrypt** (`hashlib.scrypt`) | none (stdlib, needs OpenSSL scrypt) | OWASP-listed alternative (N=2^17, r=8, p=1); memory-hard; best if a new dependency is unwanted |
  | **PBKDF2-HMAC-SHA256** | none | only if FIPS compliance is required (≥ 600 000 iterations); not memory-hard |
  | bcrypt | wheel | legacy; 72-byte input limit conflicts with long/Unicode passphrases unless pre-hashed |

  **Decision (PLR-9a, measured on the development Mac):** scrypt N=2^17, r=8, p=1 (the OWASP
  parameters) takes about 180 ms to hash and 160 ms to verify, with roughly 230 MB peak RSS in the
  measuring process; at most two hashes run at once (`MAX_CONCURRENT_HASHES`). That is acceptable for
  a trusted-network server and needs no new dependency, so **scrypt stays the default**. Argon2id
  remains a drop-in behind `PasswordHasher` (rehash on login) if a deployment wants it; re-measure
  on the real server before cutover.
- Policy: **minimum 10 characters [decided]** (named config constant `PASSWORD_MIN_LENGTH`; lower than
  OWASP's 15 for password-only accounts, accepted for a trusted-network hobby server — do not lower
  silently), support ≥ 64, allow Unicode, whitespace, paste and managers; no truncation/trimming/
  case-folding, no composition recipes or periodic rotation. Offline-capable compromised-password
  blocklist is enforced server-side: a shipped lower-cased list
  (`mtg_analyzer/data/common_passwords.txt`, only entries ≥ the minimum length) plus pattern rules (one
  repeated character, ascending/descending runs, password equal to the account name). It ships as a
  small starter list; the operator merges a larger MIT-licensed list (e.g. SecLists) with
  `backend/scripts/update_password_blocklist.py`. Bound input size before hashing; bound concurrent hashing; benchmark
  parameters on the deployment; use the library verifier.
- **Strength indicator [decided]:** the signup/password-change (and admin password-change) form shows
  a red/yellow/green meter (localized, text label as well as colour for accessibility). **Red blocks
  the submission, yellow does not.**
  - Red: shorter than `PASSWORD_MIN_LENGTH` (10; **15 for admin accounts**,
    `ADMIN_PASSWORD_MIN_LENGTH`, the admin forms use the same meter with that threshold) — and,
    server-side only, blocklisted.
  - Yellow: valid, but a recommendation is unmet: shorter than the green length (named constant,
    [proposal] 12 for players, never below the red threshold for admins), no digit, or no special character; the label says which one is missing.
  - Green: at least the green length **and** contains a digit **and** a special character.
  - Digits and special characters are *recommendations* that move yellow to green, not requirements
    (no composition rules for acceptance; a long digit-free passphrase is accepted as yellow).
  Evaluated locally from length and character classes only, the password is never sent anywhere for scoring. The blocklist is applied by the
  server on submit (clear error, no leak of the list to the client); [proposal] optionally ship a
  small top-N list to the client so the meter can show red for the commonest passwords.

**Auth API and sessions**
- `/api/auth`: signup, login, current-account, logout, logout-all, password-change. Identity comes
  from one FastAPI dependency; client-supplied owner IDs are rejected. Password change revokes other
  sessions and requires the current password.
- Session secrets: 256 random bits from the CSPRNG, only the digest is stored, accepted solely via the
  cookie (never URL/body/`localStorage`). Rotate on login and on privilege change; idle and absolute
  timeouts enforced server-side with named config values; cookie lifetime ≤ server lifetime; active
  sessions listed in the UI.
- Online: host-only `__Host-` cookie (`Secure`, `HttpOnly`, `Path=/`, no `Domain`), SameSite=Lax for
  players, HSTS. Ports are not a cookie boundary and `Path` is not an isolation boundary.
- CSRF: session-bound synchronizer token in a custom header for every mutation including multipart
  uploads; pre-login CSRF context for login/signup; no state-changing GET. Keep the existing
  exemption for clients that send neither `Origin` nor `Sec-Fetch-Site` (MCP, scripts, `TestClient`)
  **only for requests that carry no session cookie**; a cookie-bearing request must pass the token
  check regardless. Central handling in `api.js`; audit direct `fetch` calls. Credentialed CORS only
  for configured frontend origins, never a wildcard.
- Rate-limit login/signup by source and by login identifier without creating an indefinite lockout
  path; generic login failures, no enumeration or obvious timing difference for unknown/disabled
  accounts. Named config values for limits, expiry and sizes.
- Frontend: localized (DE/EN via `i18n.js`) login/signup, account state in the header/Profil flow;
  connection settings stay reachable while logged out; credentials are kept apart from gameplay
  preferences.

**Invitations [decided]**
- Signup needs a valid invitation token. Players (logged in) and admins can generate `player` tokens;
  only admins can generate `admin` tokens (§6). Token =
  256 random bits (CSPRNG), shown **once** at creation, only its digest is stored; single-use,
  expiring (named config value, [proposal] default 7 days) and revocable by its creator or by an admin.
  Delivered out of band (the UI offers copy), never put in a query string that reaches logs — the
  signup form takes it as an input field (an invite link carries it in the URL fragment, which is not sent
  to the server).
- Each token records its creator (`player_uuid` or admin id) and, once used, the new account, for audit
  and abuse tracing. Named limits: tokens a player may have outstanding at once and per day
  (`INVITE_MAX_OUTSTANDING_PER_PLAYER`, …); admins are not capped but audited. A disabled or
  deleted creator invalidates its unused tokens.
- Redemption is rate-limited by source (token guessing), failures are generic (unknown, expired,
  used and revoked look the same), and the token is consumed atomically with account creation, so
  two concurrent signups cannot share one token.
- Bootstrap: the first invitations are created in the admin **initial setup** (§6); in `--online` by
  the OS-operator-created admin; in `--localdev` the default-localuser can invite as well.
  Admin-generated tokens use the per-request password (§6). Admins can list token metadata
  (creator, state, expiry) but never read an issued token again.

**Default-localuser:** implemented here (a flagged account that only the `--localdev` loopback path
may sign in automatically; logout is allowed, then the normal login UI applies).

## 4. PLR-9b — Deck and session ownership

- Indexed deck **scope** (`global`, `private`; `unassigned` only as an invisible migration-internal state) and owner column.
  Invariants: private ⇒ player-account owner; global ⇒ no player owner; `unassigned` ⇒ invisible to
  ordinary APIs (legacy decks are migrated to `global`, see below). `NULL` ownership never means global; `author`, name or an old client token never prove
  ownership. Enforce in SQL including upsert conflicts.
- Players read global + own private decks; create always yields a private deck owned by the verified
  player; update/delete need that private owner. Foreign private and missing IDs return the same 404;
  unauthenticated 401; global writes through player endpoints fail. A copy of a global deck is a new
  private ID and never changes the source. Derived cache writes on global decks are internal with
  fixed fields.
- Cover the real routes in `api/saved_decks.py` (`/api/decks`, `/save`, `/{id}`, validation, coverage,
  delete) and audit every indirect `get_deck` consumer — `game.py`, `solo.py`, `multiplayer.py`,
  `dynamic_analysis.py`, `archetypes.py`, `mcp_seat.py` — checking permission **before** loading or
  computing cached results. A joined game uses its server-created deck snapshot and grants opponents no
  deck access. Bot/MCP deck selection is an explicit host-authorized operation; MCP keeps its
  restricted seat credentials and never receives account sessions.
- Goldfisch/Solo/Replay sessions record their owner; enforce it on view/action/undo/export so a
  session ID cannot bypass deck scoping. Preserve multiplayer perspective redaction.
- **Migration [decided]:** all existing decks are migrated as **`global`** decks. The command is
  built in 9b and executed once at the 9e cutover. It takes its own backup of the legacy stores
  and aborts if the backup cannot be verified (it never relies on an operator-held backup), then works
  on a verified copy: preview → apply, keeps IDs, metadata and caches, and is idempotent. Nobody
  "gets everything" by signing up first, and no `unassigned` state is exposed to the runtime (it
  exists only inside the migration if a row cannot be classified, and stays invisible). Players copy
  a global deck into a private one to edit it. Migration spans separate SQLite stores (decks,
  assets): resumable journal, per-store transactions, restore instructions. Runtime admin APIs
  cannot transfer private ownership or publish private decks. It runs before
  enforcement is switched on for a real install.

**Delivered in 9b (decisions taken on [proposal] points).** Saving with an unknown `id` is a 404
(creation never accepts a client-chosen id); a *visible* global id on save/delete is 403; Solo reports
a foreign or missing deck through its existing 422 "Deck existiert nicht mehr."; the assets store is
backed up and verified by the migration but not altered (ownership: PLR-16); anonymous `/api/stats`
counts global decks only; a joined table starts from per-seat deck snapshots; dynamic-analysis jobs
record their starter. Code: `services/deck_database.py`, `api/saved_decks.py`,
`scripts/migrate_legacy_decks.py`; guide: [SERVER_GUIDE.md](../Reference/SERVER_GUIDE.md) §4a.

**Delivered (PLR-16).** Assets are keyed by `owner_uuid` (store schema v1, SQL: owner or legacy name,
unique per owner and key); routes are `/api/me/...` with the owner from the session (401 anonymous,
foreign = 404, no cross-account read: the board only loads the viewer's own art, so no seat lookup
exists). Legacy rows keep `legacy_name`, owner NULL, invisible. Migration (in
`migrate_legacy_decks.py`, same backup/copy/journal guarantees) assigns nothing by default; the
operator opts in with `--assign-assets-by-name` (exact normalized match to one player account).
Account deletion removes assets via `AccountStore.add_delete_listener` / `bind_account_cleanup`;
disable keeps them; `PlayerAssetStore.purge_orphans` is the operator/admin job. Open question for
the cutover: whether name-matched assignment should ever be the default (it can hand uploads to
whoever registered the name first).

## 5. PLR-9c — Multiplayer identity and reconnect

- Bind human `LobbyPlayer` records to the verified `player_uuid`; the lobby shows the account name.
  Resolve reconnects from the session account only — remove the name-based fallback in
  `Lobby.connect` (and the REST/WS entry points), the **client token (obsolete once login exists)**
  and the legacy per-seat secret path (the BUG-39 `auth` frame then carries the session proof, not a
  secret). Bots and MCP seats keep their separate capability paths and existing restrictions.
- Authenticate sockets at upgrade (session + exact Origin) before any lobby/game snapshot is sent; a
  mismatched seat request is rejected, never silently reassigned. Extend the existing BUG-39 `auth`
  frame mechanism rather than adding a parallel one. [proposal] strict Origin validation is the CSWSH
  defence; a session-bound CSRF proof in the first frame is optional and only worth adding if a
  deployment cannot guarantee Origin (decide in 9c). Time-limit and cap unauthenticated sockets;
  validate schemas, sizes, connection counts and message rates; check authorization and session
  validity per action; disable compression unless justified.
- **Single-session lock [decided].** One account may hold one multiplayer connection at a time. A
  second tab or device using the same account is **blocked** with a visible error ("Blockiert aufgrund
  paralleler Session") instead of taking over. Mechanics [proposal]:
  - the **server** issues the `tab_id` (random, bound to the account session) on the first accepted
    connection; the client keeps it in `sessionStorage` (survives refresh) and presents it on
    reconnect. A client-chosen or guessed `tab_id` never grants a takeover, so a stolen session
    cookie cannot evict the owner. "Duplicate tab" copies `sessionStorage`: a copied `tab_id` while the
    original socket is live is treated as a different tab (the server marks a `tab_id` as bound to one
    live socket and refuses a second concurrent use);
  - no live socket for the account → accept; live socket with the **same, server-bound** `tab_id`
    whose old socket is dead or being replaced by a reconnect → replace it; otherwise close with a
    dedicated reason (`parallel_session`, code 1008) and show the error with **no** auto-reconnect
    backoff;
  - liveness via ping/pong; a socket that misses the grace window (named constant) counts as dead and
    is replaceable, so a crashed tab cannot lock the account out;
  - known consequence: after a browser restart `sessionStorage` is empty, so the player's own stale
    socket blocks them until the grace window passes (document it, not a bug);
  - scope: the multiplayer lobby/game socket. REST deck management and single-player sessions are not
    blocked. This supersedes the "takeover" behaviour of `lobby_websocket` for human accounts.
- Logout/expiry/disablement/deletion close that account's sockets and disable actions; existing
  disconnect-grace rules apply without deleting persistent data; relogin within grace resumes the seat.
  A server restart promises no recovery of in-memory games. Use a coordinated restart at rollout to
  invalidate legacy seat credentials.
- Browser refresh: load the account, reconnect to its seat, fetch a fresh authoritative view.

**Delivered in 9c (decisions taken on [proposal] points).** `Lobby.connect(player_uuid, name)` is the only
reconnect path; `LobbyPlayer.player_uuid` is never serialized and the lobby `id` stays a separate public
handle every REST route checks against the session account (`Lobby.owned_by`, 403 otherwise). The BUG-39
secret, `X-Player-Secret`, the client token (cookie, config, sweeper job) and the name fallback are
removed; bug reports for a table need the signed-in seat owner. `/ws/lobby`: cookie checked at upgrade
(`api/auth.websocket_context`), exact Origin by `request_guard`, then a required first `auth` frame
`{tab_id?, csrf_token?}` (5 s, global cap of 16 pending sockets); **decision: Origin is the CSWSH
defence, the CSRF proof is optional but verified when sent** (the frontend sends it). Frames are
size/schema/rate limited, compression is off (`setup/start.py`), the session is revalidated
(`AccountStore.session_valid`, non-sliding) per frame and every sweep. Single-session lock in
`LobbyConnectionManager.admit`: server-issued 128-bit `tab_id` bound to (account, session digest); a
live socket is replaceable only when stale (90 s without a frame) or when the same server-bound tab id
reconnects and the old socket fails a liveness probe (`liveness`/`alive`); else `parallel_session`
(1008, no frontend retry). Rename: no rename endpoint exists in 9a, so "rename only outside a
lobby/game" is deferred to whoever adds one. The PLR-4 token-expiry asset purge in `sweep_once` is gone
with the tokens; abandoned-account asset cleanup belongs to PLR-16. Code: `services/lobby.py`,
`api/multiplayer.py`, `api/multiplayer_ws.py`; tests `tests/api/test_api_multiplayer_identity.py`.

## 6. PLR-9d — Administration

**Entrypoint [decided]:** a simple static **`/admin` page** (plain forms and tables, no fancy UI) on
the one listener, e.g. `http://127.0.0.1:8765/admin`, API under `/api/admin`. Loopback only unless
`--online` (then HTTPS + MFA). This replaces the earlier host-dispatch (`admin.localhost`) idea, so
no browser name-resolution dependency.

**No stored admin session [decided]:** the admin page sets **no cookie** and the server keeps no admin
session. Each admin action sends admin name + password (plus the MFA code in `--online`) with that
request; the server verifies it per request (same `PasswordHasher`, throttled by source and identity,
generic failures) and the page asks for the password again each time (held in memory only for that
call, never in `localStorage`/URLs/logs). **[proposal] Polling:** starting a DB-update job returns a
one-time, job-bound read token (random, digest stored, expires with the job) used only to poll that
job's progress, so progress views do not re-prompt; list/read views are authorized with the password
once per page load or action batch (decide in 9d). Throttling keys on admin identity, since every
admin request comes from loopback. `/admin` gets its own strict CSP (no inline script, no external
sources) and renders player-controlled text (names, deck names, audit fields) strictly as text, since
the password is typed into the same origin as player content. With no ambient credential there is nothing for CSRF to
ride on; still enforce Origin/Fetch-Metadata checks and the loopback gate. Destructive actions
additionally show preview + confirmation. A separate URL or hidden navigation is never authorization;
player cookies are never accepted on `/api/admin` and admin credentials never log into the player UI.

**Rules**
- Dedicated admin identities that cannot log into the player frontend; explicit role on every admin
  request including reads; admins are never created through the player signup (only via admin
  invitations below, or the OS-operator command); clients cannot submit a role at registration;
  player-account APIs reject admin targets. Admin password recovery and role changes stay an
  OS-operator task.
- **Initial setup [decided]:** the first start with an empty admin table seeds one admin identity
  `admin` with the initial password `admin` (reserved name, hashed like any password, the initial
  value a documented constant, flagged `setup_required`). It exists only to open the **setup
  screen** on `/admin`, which must be completed in this order before anything else works:
  1. set a valid new admin password (admin minimum **15 characters**, `ADMIN_PASSWORD_MIN_LENGTH`;
     full policy and blocklist, not red, different from the initial one);
  2. generate the first **admin invitation(s)** and the first **player invitation(s)** (§3
     *Invitations*), shown once with a copy button.
  Until setup is complete the `admin`/`admin` credential may do nothing but this setup; every other
  admin action and every player operation is refused. The flag clears atomically once the password
  is changed; step 2 can be repeated later from the normal admin page (setup is "done" when the password
  is changed, an install may continue without creating invitations yet). Safeguards, because a
  publicly known credential is only acceptable behind the gates:
  - it works only through the loopback-only `/admin` gate (incl. the proxy rule in §3), so a LAN or
    internet client cannot use it even before the change;
  - `--online` does **not** seed it: remote admin needs MFA anyway, so there the first administrator
    is created by the OS-operator command and `/admin` stays disabled until one exists; the same
    15-character policy applies;
  - throttling and audit apply to it like any admin (audit logs "initial setup completed"); the
    initial password never appears in logs or responses, only in the docs;
  - while setup is open: startup warning and a banner on `/admin`; changing the password is a fixed
    step before the 9e cutover serves players.
- **Admin invitations [decided]:** an invitation token carries a role (`player` or `admin`). Only
  admins can create `admin` tokens; they are redeemed on a separate admin signup form under `/admin`
  (never on the player signup), the new admin chooses a name and a password that meets the 15-character
  policy, and in `--online` must enrol MFA before the account becomes active. Player tokens never
  yield an admin and admin tokens never yield a player. Role changes of existing accounts stay an
  OS-operator task.
- Remote administration (`--online`) requires MFA (protected enrollment/replacement, single-use
  recovery codes; authenticator method decided in 9d) — until then it stays disabled.
- Scope: search/list/create players; **disable/re-enable; revoke sessions; delete accounts**; list,
  create, view, edit, delete global decks; trigger allowlisted DB refresh/update jobs and inspect their
  progress. No arbitrary SQL, shell, DB wipe or general server configuration. LLM settings and quota
  tests stay OS-operator-only.
- **No admin-initiated password reset [decided].** A reset credential seen by an admin is an account
  takeover and would contradict "admins cannot read private decks". Admins disable/revoke only;
  password recovery is the audited OS-operator command (CSPRNG, expiring, single-use, digest-only
  credential that authorizes password replacement only; atomic consumption; never auto-login; revokes
  sessions; invalidates earlier credentials; delivered out of band, never in logs or support chat).
- **Account deletion [decided]:** destructive, so it needs a preview showing counts only (decks,
  assets, sessions — never content) and explicit confirmation. It removes the account, its private
  decks, assets and sessions, closes its sockets and frees the seat. The account name is tombstoned
  for a **configurable retention period, default 7 days** (`MTG_NAME_TOMBSTONE_DAYS`) before it can be
  registered again, so a deleted name cannot be impersonated immediately; the UUID is never reused.
  Admin and default-localuser accounts cannot be deleted through this path. Backup restore: keep a
  deletion journal at least as long as the backup retention and replay it after a restore (decide in
  9d/9e whether this is in scope or reduced to a documented restore step).
- Disabling blocks login and kills existing REST/WS sessions immediately without deleting data.
  Admins cannot inspect/edit/transfer private decks, impersonate players, or join/control games.
  Global-deck deletion and other destructive operations also need preview + confirmation.
- Audit log: actor, action, target, timestamp, result — no credentials or private deck contents;
  access to it is restricted. `PLR-17` owns enforcement of the allowlisted update routes including
  direct calls outside the admin UI.

**Role and resource matrix** (separate account types, no inheritance, no admin-superuser bypass;
enforced in backend dependencies and every REST/WS path, not only in navigation):

| Operation | Player | Admin |
| --- | --- | --- |
| Read global decks | Yes | Yes, through administration |
| Create/edit/delete global decks | No | Yes |
| Create/edit/delete own private decks | Yes | No private decks for admins |
| Read/edit/delete another player's private decks | No | No |
| Copy a global deck into an own private deck | Yes | No |
| Play Goldfisch/Solo/Replay/Multiplayer; host or control bot/MCP seats | Yes | No |
| Refresh/update allowlisted databases; inspect update jobs | No | Yes |
| List/create/disable/re-enable/**delete** players; revoke sessions | No | Yes |
| Generate/revoke own invitation tokens (limited) | Yes | No |
| Generate invitation tokens; revoke any; list token metadata | No | Yes |
| Initiate password reset | No | No (OS operator) |
| Read/change own profile and assets | Yes | No |
| Generate admin invitation tokens (new admins; redeemed on `/admin`) | No | Yes |
| Change an existing account's role; unrelated server/LLM configuration | No | No (OS operator) |

"Global" means visible to authenticated players on this server, not anonymously published.

## 7. PLR-9e — Protection of persistent data, rollout

- Restrict the data directory, database files, SQLite journal/WAL and backups to the service identity;
  never serve them statically or include them in exports, support bundles or version control.
- Encryption at rest is a project requirement for deployed account data and backups. Baseline: an
  encrypted host volume plus encrypted backups, provisioning documented and verified at deployment.
  **Decide at the start of 9e** whether copied database files must also be protected independently of
  the volume (SQLCipher: extra binary dependency, platform wheels, affects every store's format); the
  choice must be made before any store format is frozen. Standard SQLite is never described as
  encrypted; a password hash does not encrypt a database.
- Keys live outside the database, backups and repository (OS secret store or operator mechanism);
  define backup, recovery and rotation first; never silently fall back to plaintext on a missing key.
  Account for journals, temp files, migration backups and restores. Encryption protects stored copies
  only — a running authorized server can still read its data, so authorization, isolation and audit stay.
- Retention rules for expired sessions, reset records, audit logs and backups.
- Logging: authentication outcomes, authorization failures, session lifecycle, resets, admin data
  access, privileged mutations; sanitize untrusted fields; exclude cookies, passwords, CSRF/reset
  tokens and private payloads; restrict access; document rotation, retention, review.
- Browser output: extend `security_headers.py` (CSP, `nosniff`, `frame-ancestors`, Referrer-Policy
  already exist, BUG-44) with `Cache-Control: no-store` on credential-bearing and private
  account/admin responses; review client/service-worker caches for cross-account leakage; render
  names/decks/audit records as text or context-escaped in both frontends; no active HTML/SVG uploads
  on trusted origins.
- References (design guidance, not a compliance claim): OWASP Password Storage, Authentication,
  Forgot Password, Session Management, Authorization, CSRF Prevention, WebSocket Security,
  Cryptographic Storage and Logging cheat sheets. No claim of OWASP/ASVS compliance follows without an
  explicit verification scope and evidence from the implemented system.
- Update PLAYER_PROFILE, MULTIPLAYER, OPERATIONS, the architecture security posture, user help and
  the relevant Done catalogues from tested delivered behaviour, then close PLR-9.

## 8. Verification gates

- **Invitations:** signup without/with expired, used, revoked or foreign token fails with one generic
  error; concurrent redemption of one token creates one account; token digest only in DB/logs;
  per-player limits; disabled/deleted creator invalidates tokens; players cannot mint tokens above the
  limit or for another creator; admin cannot read an issued token again.
- **Auth/unit/API:** password verification, normalized-name collisions and concurrent signup/rename,
  expired/revoked sessions, rotation, logout, throttling, CSRF (including multipart and missing/`null`/
  spoofed Origin), CORS, forbidden owner/scope changes, password limits/blocklist/Unicode, rehashing,
  generic error and timing paths, sessions surviving a backend restart.
- **Run modes:** LAN allowlist (own subnet and VPN interface accepted, foreign address rejected for
  HTTP and WS, spoofed forwarded headers ignored), `--online` refuses HTTP, `--localdev` refuses non-
  loopback and its default-localuser is unreachable in other modes, logout of the default-localuser.
- **Authorization:** a two-players-plus-admin matrix across every deck consumer and private session
  route; cross-scope upserts, global read/copy, private isolation, invalid scope/owner combinations,
  direct database-update calls.
- **Admin:** player/anonymous requests fail on every admin route; no admin can be created through the player signup; per-request password required and no admin cookie/session is ever set; disablement revokes
  active access; deletion preview/confirm, cascade and name tombstone (default 7 days, configurable);
  no admin reset path; admins cannot read private decks, impersonate, play or control bot/MCP seats;
  privilege removal, MFA/recovery before remote admin; `/admin` reachable from loopback only by
  default, **including when reached through `frontend_proxy.py` from a LAN client (403)**; XSS payloads
  in player/deck names do not execute on `/admin`; job-bound poll token works only for its job.
- **Names/IDs:** account name is the only visible name; UUID used everywhere internally (seats,
  assets, replays, logs); rename keeps ownership; the client token no longer exists.
- **Allowlist:** (implemented in `services/network_gate.py`, `tests/services/test_network_gate.py`) `MTG_ALLOWED_NETWORKS` set → exactly those CIDRs plus loopback; enumeration failure →
  loopback only; IPv4-mapped IPv6 and invalid CIDR handled.
- **Passwords:** 10-character minimum and blocklist enforced server-side (red is rejected, yellow
  accepted); the meter's red/yellow/green classes match the server at the boundaries (9/10, 11/12
  characters, with/without digit and special character, Unicode characters and whitespace).
- **Initial setup:** `admin`/`admin` seeded once on an empty admin table and not reseeded on repeat
  starts or after deletion; before the password change only the setup screen works (other admin
  routes, invitations and player APIs refuse); a 14-character new password is rejected for admins,
  15 accepted; the initial password cannot be reused; unusable from a non-loopback address and
  through the proxy; not seeded in `--online`; startup warning and banner while setup is open; setup
  creates admin and player invitations that work once; the flag clears atomically.
- **Admin invitations:** player tokens cannot create admins and admin tokens cannot register players;
  player/anonymous callers cannot mint admin tokens; admin signup enforces the 15-character policy
  (and MFA enrolment in `--online`).
- **Multiplayer:** same-name accounts impossible; forged legacy tokens/secrets cannot reclaim seats;
  refresh resumes only the owner; **second tab with the same account is blocked and shows the error,
  same-tab refresh resumes, a dead socket does not lock the account out, a duplicated tab (copied
  `sessionStorage`) is blocked, a client-guessed `tab_id` never evicts the owner**; expiry/logout/deletion
  close sockets; hidden information and bot/MCP paths unchanged; WS first-frame failures, limits and
  idle revocation.
- **Storage:** credential leakage in DB/log/export fixtures, file permissions, encrypted backup and
  restore, missing-key failure behaviour. Never use real user data.
- **Migration:** on temporary copies — empty install, legacy decks become `global` with IDs/caches
  intact, legacy decks/assets, unclassifiable rows stay invisible and are listed in the report,
  unverifiable backup aborts, partial failure/restart, repeat execution, backup restoration; no record exposed, lost or silently reassigned.
- **Browser:** signup → save deck → refresh → join game → reconnect → logout → second-account login in
  independent contexts; stored-XSS payloads in both UIs; security headers; cache isolation; no
  credentials in URLs or snapshots. Run the full backend suite; the full-cache tier only if parser or
  engine code changed. Record a requirement-to-test mapping and resolve every open decision above
  before the cutover.
