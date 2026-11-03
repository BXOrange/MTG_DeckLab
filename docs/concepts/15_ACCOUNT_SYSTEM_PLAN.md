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
dependency at startup. Opaque immutable `account_id` for ownership; a unique normalized login name;
a separately editable display name. `Deck.author` stays descriptive credit.

- **Run modes [decided].** Three startup modes replace today's "loopback unless `--host`":

  | Mode | Start | Reachable from | Transport | Notes |
  | --- | --- | --- | --- | --- |
  | **LAN** (default) | `./start.sh` | the host's own IP ranges only (loopback, the subnets of its attached interfaces including VPN interfaces) plus operator CIDRs | HTTP allowed | accounts required; weaker cookie profile, see §3 |
  | **Online** | `--online` | any address | HTTPS only | `__Host-` cookies, HSTS, no IP allowlist; remote admin only with MFA |
  | **Local dev** | `--localdev` | loopback only (refuses to combine with LAN/online binds) | HTTP | enables the **default-localuser** |

- **Default-localuser [decided].** In `--localdev` a built-in player account (`local`) is signed in
  automatically for loopback requests and can play without a login. It can log out and be replaced by
  a real player login. It exists and is accepted **only** in `--localdev`; in LAN/online it is
  unreachable (cannot log in, no automatic session). The login-free path is opt-in, so every other
  mode behaves as a real multi-account server. Reserved names (`local`, `admin`, bot names) cannot be
  registered.
- **Admin surface [decided].** Admin and player identities are separate, admin is not a player
  superset (matrix in §6). The admin entrypoint is loopback-only in every mode; remote admin exists
  only with `--online`, HTTPS and MFA. `--localdev` keeps it reachable locally.
- **Registration** is operator-configurable. Anonymous card browsing and text-only deck parsing stay
  available; persistence and human multiplayer require a login (the default-localuser counts as a
  login in `--localdev`). No loopback bypass outside `--localdev`.
- **Unique names [decided].** Login name **and** display name are unique after normalization
  (NFKC + case-fold, trimmed, bounded length); the multiplayer player name is the display name, so
  two seats can never share a name. Signup therefore reveals "name taken" — accepted by design;
  *login* failures stay generic. Names that collide with bot names or reserved words are refused.
  Enforced by unique indexes (concurrent signup/rename tests), not by a pre-check.
- **Out of scope (follow-ups):** email verification, OAuth, private-deck sharing, user data export.

## 2. Sub-ticket map

| Ticket | Delivers | Needs |
| --- | --- | --- |
| **PLR-9a** | Run modes + IP allowlist, `accounts.db`, migrations, password hashing, sessions, `/api/auth`, CSRF/Origin extension, throttling, default-localuser, login/signup UI slice | — |
| **PLR-9b** | Deck scope/owner columns, authorization through every `get_deck` consumer, private game-session ownership, legacy-deck migration command | 9a |
| **PLR-9c** | Multiplayer identity bound to accounts, authenticated WS, single-session lock, removal of name/token/secret fallbacks | 9a, 9b |
| **PLR-9d** | Admin entrypoint + `/api/admin`: players (list/create/disable/enable/delete, session revoke), global-deck CRUD, allowlisted DB-update jobs, audit log | 9a, 9b (+ PLR-17 for update-route enforcement) |
| **PLR-9e** | Encryption at rest, backups/restore, secrets handling, security-event logging, OWASP test mapping, coordinated cutover and docs | 9a–9d, PLR-16 |

Release in dependency order; **ship enforcement and client updates together and never expose a
partially protected deployment** — the cutover (9e) is what turns enforcement on for a real
install. Each sub-ticket ships its own frontend slice. `PLR-16` (asset ownership) is a hard gate for
the cutover; without it legacy asset mutations stay disabled. Missing-card discovery (`ANA-5`) is
independent of the cutover.

## 3. PLR-9a — Run modes, storage and authentication

**Run modes and network gate**
- Extend `request_guard.py` (BUG-40/41/42) rather than adding a second guard: add a **peer-address
  allowlist** evaluated on the ASGI client address (never `X-Forwarded-For` unless the peer is a
  configured trusted proxy; the built-in `frontend_proxy.py` must forward the real client address).
  LAN allowlist = loopback ∪ subnets of the host's interfaces (VPN interfaces included) ∪
  `MTG_ALLOWED_NETWORKS` CIDRs. [proposal] enumerate interfaces with a small dependency (`psutil`) and
  fall back to the private ranges (RFC 1918, ULA, link-local, 100.64.0.0/10 for CGNAT VPNs such as
  Tailscale) when enumeration fails; log the active allowlist at startup. Applies to HTTP and WS.
- `config.py` exposes the mode; `setup/start.py` gains `--online` and `--localdev` (mutually
  exclusive; `--host` is superseded by the mode and kept only as a documented override).
- Update [OPERATIONS.md](../Reference/OPERATIONS.md) and the `CLAUDE.md` startup directive in the same
  change that makes the default flip. Starting stays offline-safe (no network needed at startup).
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

  Recommendation: Argon2id; scrypt as the zero-dependency fallback.
- Policy (OWASP): password-only accounts need ≥ 15 characters, support ≥ 64, allow Unicode,
  whitespace, paste and managers; no truncation/trimming/case-folding, no composition recipes or
  periodic rotation. Offline-capable compromised-password blocklist (shipped data file, documented
  update process) plus a local strength indicator. Bound input size before hashing; bound concurrent
  hashing; benchmark parameters on the deployment; use the library verifier.

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

**Default-localuser:** implemented here (a flagged account that only the `--localdev` loopback path
may sign in automatically; logout is allowed, then the normal login UI applies).

## 4. PLR-9b — Deck and session ownership

- Indexed deck **scope** (`global`, `private`, migration-only `unassigned`) and owner column.
  Invariants: private ⇒ player-account owner; global ⇒ no player owner; `unassigned` ⇒ invisible to
  ordinary APIs. `NULL` ownership never means global; `author`, name or an old client token never prove
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
- **Migration:** an OS-operator command previews explicit mappings (legacy deck → player account or
  global catalogue) and keeps IDs, metadata and caches. [proposal] ship a bulk mode
  ("assign all `unassigned` decks to account X") as the documented path for the common single-user
  install, so an upgrade is one command and never "first signup gets everything". Migration spans
  separate SQLite stores: resumable journal, per-store transactions, verified backups, restore
  instructions. Runtime admin APIs cannot transfer private ownership or publish private decks.

## 5. PLR-9c — Multiplayer identity and reconnect

- Bind human `LobbyPlayer` records to verified account IDs; the lobby player name is the account's
  unique display name. Resolve reconnects from the session account only — remove the display-name
  fallback in `Lobby.connect` (and the REST/WS entry points), the PLR-4 client token and the legacy
  secret path. Bots and MCP seats keep their separate capability paths and existing restrictions.
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
  - the client creates a `tab_id` (`sessionStorage`, survives refresh, differs per tab) and sends it
    on connect;
  - no live socket for the account → accept; live socket with the **same** `tab_id` (refresh,
    reconnect after a drop) → replace it; live socket with a **different** `tab_id` → close with a
    dedicated reason (`parallel_session`, code 1008) and show the error with **no** auto-reconnect
    backoff;
  - liveness via ping/pong; a socket that misses the grace window (named constant) counts as dead and
    is replaceable, so a crashed tab cannot lock the account out;
  - scope: the multiplayer lobby/game socket. REST deck management and single-player sessions are not
    blocked. This supersedes the "takeover" behaviour of `lobby_websocket` for human accounts.
- Logout/expiry/disablement/deletion close that account's sockets and disable actions; existing
  disconnect-grace rules apply without deleting persistent data; relogin within grace resumes the seat.
  A server restart promises no recovery of in-memory games. Use a coordinated restart at rollout to
  invalidate legacy seat credentials.
- Browser refresh: load the account, reconnect to its seat, fetch a fresh authoritative view.

## 6. PLR-9d — Administration

**Entrypoint [proposal — options and recommendation]**

| Option | How | Verdict |
| --- | --- | --- |
| A. Second uvicorn `Server` task on a loopback port, same process | keeps one process; but same host `localhost` ⇒ shared cookie jar | acceptable only with distinct cookie names |
| **B. Host dispatch on the one listener** | admin routes answer only to a dedicated hostname (`admin.localhost` locally, a configured admin hostname online), only from loopback unless `--online` | **recommended**: one process, distinct origin and cookie jar (browsers resolve `*.localhost` to loopback), reuses the request guard |
| C. Separate admin process | strongest isolation | breaks "one uvicorn process on purpose" (session manager, lobby and jobs share memory) |

With B: add the admin host to the Host allowlist, admin cookie name/`purpose` distinct from player
sessions, admin sessions server-side with short expiry, SameSite=Strict, CSRF/Origin protection and
reauthentication for sensitive changes. Verify `*.localhost` resolution in Safari/Chrome/Firefox
during implementation. A separate URL or hidden navigation is never authorization.

**Rules**
- Dedicated admin identities that cannot log into the player frontend; explicit role on every admin
  request including reads; first administrator is created by a local OS command, never by signup;
  clients cannot submit a role at registration; player-account APIs reject admin targets. Admin role
  provisioning/recovery stays an OS-operator task.
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
  decks, assets and sessions, closes its sockets and frees the seat. [proposal] the login/display name
  is tombstoned for a named retention period before reuse so a deleted name cannot be impersonated
  immediately; admin and default-localuser accounts cannot be deleted through this path. Define
  restore semantics for backups (deletions replayed after a restore).
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
| Initiate password reset | No | No (OS operator) |
| Read/change own profile and assets | Yes | No |
| Assign admin roles; unrelated server/LLM configuration | No | No (OS operator) |

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

- **Auth/unit/API:** password verification, normalized-name collisions and concurrent signup/rename,
  expired/revoked sessions, rotation, logout, throttling, CSRF (including multipart and missing/`null`/
  spoofed Origin), CORS, forbidden owner/scope changes, password limits/blocklist/Unicode, rehashing,
  generic error and timing paths, sessions surviving a backend restart.
- **Run modes:** LAN allowlist (own subnet and VPN interface accepted, foreign address rejected for
  HTTP and WS, spoofed forwarded headers ignored), `--online` refuses HTTP, `--localdev` refuses non-
  loopback and its default-localuser is unreachable in other modes, logout of the default-localuser.
- **Authorization:** a two-players-plus-admin matrix across every deck consumer and private session
  route; cross-scope upserts, global read/copy, private isolation, invalid scope/owner combinations,
  unassigned legacy rows, direct database-update calls.
- **Admin:** player/anonymous requests fail on every admin route; bootstrap cannot be claimed through
  signup; disablement revokes active access; deletion preview/confirm and cascade; no admin reset path;
  admins cannot read private decks, impersonate, play or control bot/MCP seats; admin-host/cookie
  separation, privilege removal, MFA/recovery before remote admin; loopback-only default.
- **Multiplayer:** same-name accounts impossible; forged legacy tokens/secrets cannot reclaim seats;
  refresh resumes only the owner; **second tab with the same account is blocked and shows the error,
  same-tab refresh resumes, a dead socket does not lock the account out**; expiry/logout/deletion
  close sockets; hidden information and bot/MCP paths unchanged; WS first-frame failures, limits and
  idle revocation.
- **Storage:** credential leakage in DB/log/export fixtures, file permissions, encrypted backup and
  restore, missing-key failure behaviour. Never use real user data.
- **Migration:** on temporary copies — empty install, legacy decks/assets, ambiguous mappings, partial
  failure/restart, repeat execution, backup restoration; no record exposed, lost or silently reassigned.
- **Browser:** signup → save deck → refresh → join game → reconnect → logout → second-account login in
  independent contexts; stored-XSS payloads in both UIs; security headers; cache isolation; no
  credentials in URLs or snapshots. Run the full backend suite; the full-cache tier only if parser or
  engine code changed. Record a requirement-to-test mapping and resolve every open decision above
  before the cutover.
