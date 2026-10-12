# CLAUDE.md — project wiki for Claude

Orientation for working in this repo. Keep it current when you change
architecture, conventions, or the rules-engine feature set.

## What this is

An MTG (Magic: The Gathering) deck analyzer with a **rules-accurate game
engine**. The headline feature is the **"Goldfisch" (goldfish) mode**: play a
saved deck against the real backend rules engine — step through the turn, play
lands, tap mana, cast spells with the stack, attack, all validated server-side
against the Comprehensive Rules (referenced as `RULE <n>` throughout the code).

Two halves:

- **`backend/`** — Python (FastAPI). The card model, rules engine, oracle
  effect IR, and the game-session API. This is where the depth is.
- **`frontend/`** — a static, buildless ES-modules app (no bundler). Tabs for
  deck import/analysis, saved decks, the goldfish board, **"Solo gegen
  Bots"** (the Multiplayer engine — real turns, priority, hidden hands —
  against 1–3 bots, with no lobby/socket; `soloView.js` + `api/solo.py`),
  the **"Replay"** board editor (a.k.a. puzzle mode), the card cache,
  Multiplayer (**Setup** = lobby + game configuration, **Board** = the
  shared game, disabled until you're at a table), and
  an **"Engine-Status"** tab documenting engine coverage, plus two header icon
  buttons: **"Einstellungen"** (`connectionSettingsView.js` — automatic backend connection, data updates and
  optional server-wide LLM configuration) and **"Profil"**
  (`profileView.js` — everything player-facing: player name, multiplayer
  default settings, auto-pass / board-comfort toggles, player-uploaded token
  art + card-back sleeves, favorite decks). Anything about *who you are* /
  *how you play* is Profil; anything about *reaching/configuring the server* is
  Einstellungen. UI language is **German**; MTG keyword names stay
  English ("Flying", "Trample").

The **Replay/Puzzle mode** is the goldfish's sibling: instead of playing a
legal deck from turn 1 you *construct an arbitrary board* (1 player = puzzle, or
2 = with an opponent) and play from there. It reuses the same `GameSession`/
`GameEngine` — a session with `mode="replay"` and `require_setup=False` plus
a family of `edit_*` actions (`services/game_session.py`) that mutate state
directly (add/remove/move objects+tokens, tap, flip, counters, life, poison,
player counters, commander damage, turn/phase). Save/load is JSON export/import
of a **re-resolvable descriptor** (`services/replay.py`: `serialize_replay`
/ `build_replay_engine` — the models have no `from_dict`, so cards are stored
by id/name and rebuilt from the cache; tokens carry a self-describing block).
Replay descriptors carry exported `instance_id` values so Aura/Equipment
attachments are remapped to rebuilt object IDs after import. Legacy exports
without these IDs cannot reliably reconstruct numeric attachment references.
`GET /api/game/{id}/replay-export` works for a goldfish session too, so a
goldfish position can be exported and re-opened in Replay. Frontend:
`frontend/src/js/replayView.js`.

Replay descriptors preserve each player's `turns_taken` and the starting seat,
so own-turn casting restrictions retain extra/skipped turns independently of the
display round. Older descriptors infer ordinary seat order. Editing the turn
recomputes these counts, including when moving backwards. Blocking offers expose
per-creature mana taxes; the shared board confirms payment before submission,
and explicit API declines leave mana and combat unchanged (RULE 509.1c–f).

## Subsystem notes (moved out; load on demand)

Invariants that must hold everywhere; details are in `docs/Reference/`:

- **Multiplayer**: `services/lobby.py` is rules-free (people/tables), `services/game_session.py` is the game. Actions carry an actor; `view(perspective=...)` redacts hidden zones server-side (RULE 400.2); RULE 117 priority is opt-in per session and only the priority holder may act. See [MULTIPLAYER.md](docs/Reference/MULTIPLAYER.md).
- **Bots** play only through the client surface (`session.view(perspective=<own id>)` + own `legal_actions` via `apply_action(..., actor_id=...)`); never read `engine.state` from a bot. See [BOTS.md](docs/Reference/BOTS.md).
- **Per-mechanic engine behaviour** (choices, copies, costs, Miracle, take-backs of resolution state, …): [ENGINE_MECHANICS_NOTES.md](docs/Reference/ENGINE_MECHANICS_NOTES.md).
- **Profil / uploaded art / saved-deck fields** (`author`, `is_cube`, `sleeve_id`; preserved-on-omission on re-save): [PLAYER_PROFILE.md](docs/Reference/PLAYER_PROFILE.md).
- **Deck analysis**: [MANA_ADVICE.md](docs/Reference/MANA_ADVICE.md) (land/ramp odds), [COMMANDER_SPELLBOOK.md](docs/Reference/COMMANDER_SPELLBOOK.md) (combo snapshot, Bracket signals).

## Run & test

```bash
# Full app (frontend static server on http://localhost:8765; sets up backend venv)
./start.sh                     # add --backend-tests to also run pytest

# Backend tests directly (do this after any backend change)
cd backend && python -m pytest -q                    # with the venv already active
# or, from any shell/interpreter, no active venv needed:
python backend/scripts/run_tests.py [pytest args...]  # resolves venv/venv_win itself
```

The backend FastAPI app is `mtg_analyzer.api.app:app`. There is **no JS build
step** or required Node runtime — edit `frontend/src/**` and reload. Optional
frontend linting is available through the project-local environment created by
`setup_dev.sh`; there is no JS test runner. Validate backend changes with
pytest (the suite is fast, ~500+ tests, keep it green).

For non-trivial frontend changes, use the real-browser verification available
through Playwright in `backend/venv`, driving Chromium against the static
frontend server and running backend, rather than relying only on API replay.

**A browser only ever needs to reach the backend's port.** `setup/start.py`
still runs two processes (backend `uvicorn`, frontend `no_cache_server.py`),
but the backend reverse-proxies anything outside `/api`/`/ws` straight
through to the frontend process (`api/frontend_proxy.py`,
`config.FRONTEND_ORIGIN`, default `http://127.0.0.1:8765`) — a
server-to-server call, not subject to CORS. `run_servers()` opens the
browser at the backend port, not the frontend one; the frontend process
stays loopback-only and isn't meant to be opened directly. This is why
`_LOCAL_DEV_ORIGIN_REGEX` in `api/app.py` only ever had to admit
`localhost`/`127.0.0.1` origins — the two-origin problem it exists for is
now the exception (`--frontend-only`), not the default path.

**Reachable from other computers on the network is opt-in, via
`start.py --host HOST`** (passed straight through as uvicorn's own
`--host`; omitted by default, so uvicorn's loopback-only default applies
unchanged). This app has **no authentication** — anyone who can reach the
host/port can read and write saved decks, player uploads, and play in any
game, so this must never become the default. Only the backend needs to
bind beyond loopback; `no_cache_server.py` stays loopback-only always (the
backend proxies it internally, same-machine only). On macOS, binding
beyond loopback triggers the OS's "Local Network" privacy permission,
which is unreliable for an unsigned CLI script (see
`no_cache_server.py`'s own comment on why *it* never does this) — the same
risk now applies to the one process that does. `settings.js`'s
`DEFAULT_SERVER_URL` defaults to `window.location.origin` (not a
hardcoded `localhost:8000`) for exactly this reason: a browser loading the
app via a LAN IP must have its own API calls resolve to that same IP, not
to its own machine's `localhost`.

**Starting is offline-safe, and must stay that way.** `start.py` calls
`setup/install.py`'s `ensure_backend_venv()` on every run, so anything that
does gets to decide whether the app can start without internet: it installs
with `pip --no-index` first (an already-complete venv is verified locally in
~0.2s, opening no socket) and only falls back to an index-using run when
that fails; a fresh venv can be built offline from the wheelhouse
`setup/install.py --download-wheels` caches in `setup/wheels/`. Nothing else
in a start reaches the network — the frontend loads no external script/font/
image, card data and art come from `backend/cache/`, and tokens/dungeons/
variant cards are committed JSON in `mtg_analyzer/data/`. Don't reintroduce
an unconditional `pip install --upgrade pip` (it always queries PyPI);
`backend/tests/test_setup_offline_start.py` pins this down.

**A plain `pytest -q` skips a whole tier.** Tests that need the real ~35k-card
cache (every `test_cube_batch_*` module, plus anything marked `full_cache`) are
opt-in: `pytest --full-cache` or `MTG_FULL_CACHE_TESTS=1`
(`tests/conftest.py`). They read an *isolated* cache — `backend/conftest.py`
redirects `MTG_CACHE_DIR` to `backend/cache/test/` and seeds it itself, so they
never touch the production `backend/cache/db/cards.db`, and **never export
`MTG_CACHE_DIR` at the production cache to run tests**: that `setdefault` is
the only thing standing between a test run and a wiped 35k-card cache. Run the
tier before closing anything that changes engine or parser behaviour — an
opt-in tier accumulates stale assertions at exactly the rate the rest of the
codebase improves, and ENG-38 closed six of them at once (five were pins that
had quietly stopped describing the engine, one was a live bug).

**Stuck-test detection is automatic** (`backend/pytest.ini`, `pytest-timeout`):
any single test running past 20s aborts with a `Timeout (>20.0s) from
pytest-timeout.` traceback naming it, instead of hanging the run — no
extra flag needed, plain `pytest -q` already has it. `backend/scripts/
run_tests.py` is a thin wrapper (`python scripts/run_tests.py [--hard-timeout
SECONDS] [pytest args...]`) adding a hard wall-clock ceiling (default 120s)
on the *whole run*, for the rarer hang the per-test timer can't reach
(collection, a session-scoped fixture, or a true C-level block) — it kills
the process group and reports the last test that had started.

## Project skills — Claude Code and Codex

Seven project-scoped skills have their canonical workflows and helpers in
`.claude/skills/`. Codex discovers matching entrypoints in `.agents/skills/`;
each loads the shared workflow and resolves resources at their original paths.
Use the relevant skill (not an ad hoc reimplementation) for the work it covers.
In Codex, invoke a skill explicitly with `$extend-parser`, `$game-engine`, etc.,
or let automatic selection choose it. Start a new session after adding skills
if the current session's skill catalog has not refreshed.
Maintain workflows, scripts and references in `.claude/skills/`; keep the Codex
entrypoint's name and concise trigger description aligned when its scope changes.
On Windows, run helpers with the available backend venv's `Scripts/python.exe`
and adapt Bash examples to PowerShell while preserving their working directory.

Skills: `extend-parser`, `game-engine`, `hand-author-card`, `singleton-sweeper`,
`inspect-db`, `understand-card`, `ticket-management`. Each skill's `SKILL.md` documents its helper scripts.

Agents (`.claude/agents/`): **`ticket-grinder`** (run as the main-thread agent:
`claude --agent ticket-grinder`; loops over eligible backlog tickets, commits and
pushes) delegates each ticket to **`ticket-worker`** (Sonnet, medium effort).

## Architecture & data flow

```code
Card (models/card.py)            immutable printed characteristics
  └─ GameObject (models/game_object.py)   one instance in a zone, mutable state
GameState (models/game_state.py)  battlefield/stack/players/turn + event bus
RulesEngine (game/rules_engine.py) rules primitives: cast, damage, draw, SBAs…
GameEngine  (game/game_engine.py)  turn/phase loop, actions, legal_actions, combat
GameSession (services/game_session.py) wraps an engine: snapshots/undo, wire view
API (api/game.py)  ── JSON ──▶  frontend (src/js/goldfishView.js)
```

Before-entry instruction choices retain their permanent and stack item in
`GameState.pending_permanent_entry`, so identity lookup survives rollback.
`entry_effect` uses the ordinary choice machinery before the entry event.

Inserted turn phases live in `GameState.turn_steps`, so snapshots retain extra
combats and their phase-specific delayed triggers through undo.

`RulesEngine`/`GameEngine` are each a **composition of per-responsibility
mixins** (ENG-20/21, 2026-07-29) rather than one file holding every method —
`game_engine.py`/`rules_engine.py` themselves shrank to `__init__` + (for
`RulesEngine`) the RULE 616 replacement-effect core + the class declaration;
everything else lives in `game/engine/*_mixin.py` (turn loop incl.
`new_game`, combat, casting, lands, activation, mana, legal_actions, misc)
and `game/rules/*_mixin.py` (triggers, casting resolution, damage/death,
draw/discard, mana/counters, copies, search, state-based actions, misc
systems). This is invisible from outside `game/`: both classes keep their
exact public method names/signatures, so `engine.cast_spell(...)`/
`rules.deal_damage(...)`/etc. still work exactly as before, and searching by
method name (grep/IDE) finds the right file regardless of which mixin
defines it.

Oracle-text → behaviour pipeline (docs/09):
`AbilitySpec` IR (`parser/oracle/spec.py`, pure JSON-shaped data, the security
boundary) → **binder** (`game/effect_binder.py`) → live `GameEffect` objects via
the `EffectRegistry` (`game/effects.py`). **Bind-on-load** is wired:
`build_goldfish_engine` calls `bind_from_catalogue(obj)` for every object it
creates, sourcing specs from `game/ability_catalogue.py` — now split into
`game/card_registry/` (`core.py`'s `register`/`specs_for` mechanism,
`families.py`'s `register_family`) and its content sibling
`game/card_catalogue/` (one hand-authored module per card, e.g. Evolving
Wilds' fetch, alphabetically foldered — see below) **and** the oracle-text
front-end. That front-end (`parser/oracle/`, docs/09 Phase 1) is `normalize` →
`segmenter` → `catalogue/handlers` (effect families over shared
`catalogue/subgrammars`) → `gate.parse_oracle`, which returns `AbilitySpec`s +
a fail-closed `MODELED`/`UNMODELED` coverage verdict. `specs_for` falls back to
it for *unregistered* cards, adding effect/triggered specs only when the card is
fully `MODELED` (never half-resolving). The front-end has **no `game/` imports**
(the security boundary); binding stays the binder's job.

### Key game/ modules

- `effects.py` — effect hierarchy + `EffectRegistry` (whitelisted `type` →
  factory). One-shot effects, `TriggeredAbility`, `ActivatedAbility`,
  `StaticEffect` (phase-skip), `StaticAbility` (layer system), `ReplacementEffect`.
- `combat.py` — combat/evasion **keyword recognition** (off Scryfall `keywords`
  & oracle text) and the rules they impose (blocking legality, damage steps).
- `continuous.py` — the **RULE 613 layer engine**. `recompute(state)` re-derives
  every battlefield permanent's characteristics in layer order and stamps
  derived P/T, types, granted keywords + a per-object `static_trace`.
  All-creature-type grants expand only the CR creature subtypes; entry triggers see
  derived types. Base-P/T filters read layer-7b values before counters.
  Squirreled Away is fully modeled (85/85); see the Deck/Cube Playability Batches
  in `docs/implementation-state/Done_Backend.md` for reusable engine support.
- `blitz.py` — Blitz payments, grants, discounts and delayed sacrifice (RULE 702.152).
- `rooms.py` — Rooms (RULE 709.5): door designations, per-door ability binding,
  `unlock`/`lock` and their `DOOR_UNLOCKED`/`ROOM_FULLY_UNLOCKED` events; the
  special action is `engine/rooms_mixin.py`, the instruction `effects/rooms.py`.
- `costs.py` — regex parser for **activated-ability costs** (`Cost: Effect`).
- `card_registry/` — card→`AbilitySpec` registry mechanism (bind-on-load
  source, née `ability_catalogue/`): `core.py`'s `register`/`specs_for`
  (also falling back to the oracle-text parser, `parser/oracle/gate.
  parse_oracle`, for unregistered `MODELED` cards + `enters_tapped`, RULE
  614.1, oracle-derived) and `families.py`'s `register_family` for a
  mechanically-identical cycle. The actual card *content* — one
  hand-authored module per card — lives next door in `card_catalogue/`
  (see "Hand-authored card catalogue layout" below), not in this package;
  the two names are deliberately parallel (registry = mechanism, catalogue
  = content) after `ability_catalogue` stopped describing either half well
  once card content moved out of it.
- `targeting.py` — legal-target computation (RULE 115 / 601.2c).
- `mana_abilities.py`, `models/mana_cost.py`, `models/mana_pool.py` — mana.

### Hand-authored card catalogue layout (`game/card_catalogue/`)

2026-09-16: with hand-authoring now the dominant way new individual cards
get added (the parser front-end's marginal gains are mostly *generalizable*
handlers, not one-off cards any more — see the "Oracle-text parser" summary
below), the ~990 hand-authored card entries were pulled out of the former
`ability_catalogue/`'s ~20 thematic modules (`black.py`, `graveyard.py`,
`damage_prevention.py`, `special_mechanics.py` for everything that didn't
fit a theme, …) into their own sibling package, **one file per card**, so a
card's entry is a `git log`/`grep`-able unit instead of one factory buried
among ~50-170 others in a themed file that had stopped meaning much once
"does this fit `black.py`'s theme" became less useful than "which file is
this card in". The old package was then renamed `card_registry/` (from
`ability_catalogue/`) since "catalogue" no longer described a package
holding zero cards — it's the registration *mechanism* `card_catalogue`
calls into, not a catalogue of anything itself:

- `game/card_catalogue/<letter>/<slug>.py` — `<letter>` is the card's
  registered name's lowercased first letter (`a`/`b`/`c`/…; no `x` yet;
  `misc`/`0-9` are reserved for a name that doesn't start with a letter,
  not currently needed), `<slug>` is the name lowercased with runs of
  non-alphanumerics collapsed to `_` (e.g. `c/circle_of_solace.py`, `t/
  the_master_gallifreys_end.py`). Exactly one `def _card() -> list[
  AbilitySpec]: ...` + `register("Card Name", _card)` pair per file — the
  same shape every hand-authored entry has always had (see the authoring
  guide), just no longer sharing a file with a hundred siblings.
- `game/card_catalogue/_shared/` — the one carve-out: helpers genuinely
  reused by **several** cards that don't fit `register_family`'s
  single-`EffectSpec`-shape template (e.g. `_shared/licid.py`'s `_licid`
  factory for the Tempest Licid cycle, MEC-47 — 13 cards, one shared
  become-Aura/revert mechanism, each own file importing it). Not a letter
  folder, not swept by `card_catalogue/__init__.py`'s import list; each
  member imports it directly. Reach for this only once ≥2 cards need the
  same non-trivial helper — a single card's own private constant/helper
  stays inlined in that card's own file instead (unchanged from before).
- A mechanically-identical **cycle** (Circle of Protection/Rune of
  Protection, `families.register_family`) still gets one file per member —
  `register_family` takes an `entries` list, so a single-entry list per
  file is exactly as valid as one call registering the whole cycle; the
  shared template's own doc comment is duplicated across every member's
  file rather than centralized, since each file has to stand on its own.
- `game/card_catalogue/__init__.py` explicitly imports every letter
  subpackage (`from . import a, b, c, …`), and each letter's own
  `__init__.py` explicitly imports every card module in it — mirroring
  `card_registry/__init__.py`'s former per-module import list: stable
  and grep-able rather than a directory scan. `card_registry/__init__.py`
  pulls in `card_catalogue` itself (after `.core`'s `register` is bound,
  so this isn't a circular import — `card_catalogue`'s own modules import
  `register`/`register_family` straight from `card_registry.core`/
  `.families`, never through the parent package) so every existing call
  site that does `from .. import card_registry` to trigger registration
  keeps working unchanged; nothing outside `card_registry/` needed to
  change for the split, and the later rename was a mechanical identifier
  swap across both packages plus every call site (no behavior change).
  Verified byte-for-byte behavior-preserving at migration time:
  `registry_signature()` unchanged, and every one of the ~990
  factories' own `repr()`'d output diffed identical against the pre-move
  code.
- The **`hand-author-card`** skill/`author_card.py` targets this layout —
  `scaffold` prints the exact `card_catalogue/<letter>/<slug>.py` path plus
  the imports a new standalone file needs (not a snippet to paste into an
  existing themed file), and `similar`/`check` search the whole
  `card_catalogue/` tree. See
  [11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)
  for the field-by-field how-to.

## Implementation state (summary)

This is orientation only. The mechanic-by-mechanic detail — what shipped,
*why* it was built that way, which tests cover it — lives in
[docs/implementation-state/Done_Backend.md](docs/implementation-state/Done_Backend.md),
organized by subsystem (Rules Engine, Game Engine, Card-type coverage, …).
Open gaps and exactly what's left on a partial feature live in
`docs/implementation-state/BACKLOG.md` (tickets by category). The user-facing
version is the frontend **Engine-Status tab**
(`frontend/src/js/implementationStatusView.js`) — keep it in sync when engine
coverage changes. Search those for a mechanic's name rather than re-deriving
its state from the code or duplicating detail here.

**The rules engine is broadly complete.** Implemented, in brief:

- **Turn structure** — full turn/phase/step loop, the stack, RULE 117
  priority (opt-in per session, played out for real in multiplayer), the
  RULE 704 state-based-action pass, all agreed-on mulligan procedures.
  RULE 724.2's `end_combat_phase` skips the current combat's remaining steps
  while preserving any separately scheduled additional combat.
- **Mana** — the whole model (generic/colour/colourless/hybrid/mono-hybrid/
  Phyrexian/{X}), RULE 605.3a spend restrictions, "any combination of
  colours", hand-zone mana abilities, triggered mana abilities.
- **Combat** — every common keyword incl. landwalk; the full RULE 508/509
  restriction / requirement / multi-block family (plain flags and qualified
  forms, board-count thresholds, group-scoped qualifiers); goad.
- **Continuous effects** — the RULE 613 layer system (layers 1–7, dependency
  pass, `EffectRegistry`-bridged for every parsed/hand-authored static
  shape); RULE 613.6 conditional statics and RULE 611 durations as two
  general systems (`game/static_conditions.py`, `game/durations.py`);
  attachment (Aura/Equipment/Fortify/Reconfigure).
  Turn-scoped cast/activation restrictions can pin a target player; named-card
  cost taxes share the existing `card_name_from_source` selector. Temporary
  flash permissions support a type-filtered next-spell grant, consumed at cast.
- **Abilities** — activated (incl. loyalty `[±N]`/`[-X]`), triggered, RULE
  616 replacement effects; interactive ordering and interactive
  target / "you may" choices; RULE 603.7 delayed triggers; RULE 608.2
  suspended resolutions. Random triggered modes use the same choice dispatcher
  before their target selection. Graveyard grants can require a current-turn
  arrival from outside the battlefield and make a cast permanent enter tapped;
  temporary grants can offer one spell from a shared batch in any graveyard.
  Transmute (RULE 702.53) binds to a hand-zone discard ability at sorcery
  speed, using the ordinary search choice for the source's exact mana value.
  Its search publicly reveals the find before moving it; public REVEAL events
  appear in the shared table feed with card images when an ID is available.
- **One-shot effect library** — damage, draw, discard, destroy, counter,
  search/tutor, mill, exile, tap, counters, pump, scry/surveil, token
  creation, copy, cascade/discover, proliferate, fight, board wipes, and
  most one-shot families the parser emits.
- **Keyword actions** — every RULE 701 keyword action has an engine
  primitive (PAR-29, closed); Empower Jace (MEC-110, RULE 701.71) creates
  and empowers Jace planeswalker tokens with live loyalty abilities and
  an untargeted choice among multiple tokens.
- **Recent keyword/defined-term mechanics** — Gift (RULE 702.174: opponent
  choice, resolution/ETB delivery, promised-gift branches and targets) and
  Expend (RULE 700.14: per-turn spell-mana thresholds) are engine-backed and
  parser-reachable.
- **Designations & subsystems** — planeswalkers, commander damage + tax,
  Monarch, Initiative, The Ring, emblems, Speed, the Case solve machine,
  energy, poison/infect/wither/toxic; controlling another player's
  turn/combat (RULE 720 — Mindslaver/Emrakul family; `GameState.
  TurnControl` + `GameSession` decision routing).
- **Card-type structures** — DFC transform + day/night/daybound; meld
  (RULE 701.42 — exile the pair, one melded permanent, un-melds on leave);
  modal-DFC/Adventure/Split-Fuse/Prepared casting; Sagas, Class/Leveler/
  Station level-ups; battles (RULE 310); face-down permanents (morph/
  manifest/disguise/cloak); dungeons + venturing (RULE 309); Rooms (RULE
  709.5 — `game/rooms.py`: a Room permanent keeps both halves and
  `GameObject.unlocked_doors` are its designations; **abilities are bound
  only for unlocked doors**, so a locked half simply has none; live names,
  mana costs, mana values, colours and rules text also follow the doors.
  Printed identity stays available for Replay and art. The unlock
  special action is `GameEngine.unlock_door`, "when you unlock this door" is
  a `DOOR_UNLOCKED` trigger with `{"filter": {"door": "this"}}` the binder
  fills in per half, and a Room's parser/coverage verdict reads **both**
  halves — `card_registry.is_authored_card`, not `is_registered(name)`);
  the RULE 9 casual variants (Planechase/Archenemy/Vanguard).

**The oracle-text parser is the main ongoing effort.** Pipeline:
`normalize` → `segmenter` → `catalogue/handlers` → `gate.parse_oracle`,
returning `AbilitySpec`s plus a fail-closed `MODELED`/`UNMODELED` verdict (a
card gets parsed effects only when *every* clause is claimed — never
half-resolved). It covers most one-shot effect families, ETB/dies/attacks/
blocks/Saga-chapter triggers with RULE 603.1 subject scoping, `<cost>:
<effect>` activated abilities, modal spells, additional cast costs, the
counter family, enters-tapped / enters-with-counters clauses, static
anthem/lord clauses, graveyard recursion, and much of the RULE 701 keyword
trail. The RULE 702 keyword catalogue (~195 rows,
`parser/oracle/catalogue/keywords.py`) is parser *recognition* only — not
proof of engine behaviour; don't cite a keyword as implemented from the
catalogue's mere existence.

Phase-trigger bodies can bind "that player" to the active player (PAR-100),
including linked instructions and optional choices. The acting player is
preserved across suspended effects. Additional draws accept fixed plural
counts; Teferi's Puzzle Box uses hand-to-library ordering followed by a draw
of the saved hand size, and Academy Loremaster uses a turn-scoped spell tax.

**Coverage: 60.2% (21,103 / 35,046) as of 2026-10-12, measured at
PARSER_VERSION 630** (parser-`MODELED` or hand-`AUTHORED`, measured against
the full ~35k-card Oracle universe from `scripts/import_bulk.py`, excluding
Sticker Sheet inserts by type line under RULE 123.2). Re-measure
with `scripts/coverage_report.py` (ledger-backed, `services/coverage_db.py`)
before trusting this number. The last measured **Commander-legal** slice — the subset that
matters for Goldfisch/Deck-Analyzer — was **63.4% (20,321 / 32,068)** at v630; measure
it with `scripts/coverage_report.py --commander-legal-only` (records a
separate `…-commander` snapshot row) and segment the still-UNMODELED
remainder by *cause* (wrapper re-measure / recurring template → `PAR-*` /
set-specific → `PAR-*` / missing primitive → `MEC-*` / bespoke hand-authoring
tail) with the read-only `scripts/commander_tail_report.py`. A shipped
handler's own narrative — what it does and why it was built that way —
belongs in `Done_Backend.md` under the primitive's subsystem heading, not
here; the long-tail strategy (recurring lessons, worked samples, known-open
clusters) is in `docs/implementation-state/PARSER_LONG_TAIL.md`. Open parser
tickets are `PAR-*` in `BACKLOG.md`. **Stickers (RULE 123) are a permanent
project non-goal** — the gate classifies any "sticker" card as
`NEVER_SUPPORTED`, a verdict distinct from `UNMODELED` and kept out of both
the covered count and the backlog ranking.

**Notable open gaps** are tracked with exact scope in `BACKLOG.md`:
Doomsday's "exile up to five cards in a pile";
the oracle
coverage of the battle pool (the RULE 310 engine is done, ~12 of 39 cached
battles MODELED); and assorted rough edges on already-shipped features.
**PAR-30** — PAR-29's residual per-card effect-body grammar — is the current
parser push.

Hand-authoring a card's abilities directly (rather than waiting on the
oracle-effect front-end, or for a replacement-clause/conditional-trigger the
front-end can't express yet) goes in `game/card_catalogue/` — see
[docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)
for the field-by-field how-to and the full `EffectSpec`/layer whitelist.

Implementation state is five kinds of document, kept strictly apart —
**open points**, **worklogs**, **examples**, **singleton queue**, **working
memory** — all under
`docs/implementation-state/`:

| Kind | File | Rule |
| --- | --- | --- |
| Open points | `BACKLOG.md` | The *single* backlog, backend **and** frontend, as categorized tickets (`ENG` game engine, `PAR` parser, `MEC` game mechanics, `PLR` player management, `VIS` visuals, `DB` database, `ANA` deck analysis, `BUG` bugs in shipped behaviour — the former `TYP` card-types category is retired, RULE 300–315 being complete). Open scope only — no history, and no *residue*: a partly done ticket stays here only as its terse open point (id, title, one-clause scope). **Up-for-scheduling work only**; parked/low-priority tickets and permanent non-goals move to `DEFERRED.md` so this file stays cheap to read in full. |
| Parked / non-goals | `DEFERRED.md` | Low-priority or large-and-unscheduled tickets pulled out of `BACKLOG.md` (they keep their id + full write-up), plus the "never to be built" guardrails (Stickers, Attractions, Vanguard avatars). Same open-scope-only discipline. Promote by moving a block back into `BACKLOG.md`. |
| Worklogs | `Done_Backend.md`, `Done_Frontend.md` | Catalogues, organized by game-mechanic/app-area (not chronologically) — what shipped and *why it was built that way*, one entry per feature/primitive under a subsystem heading. Entry headings are the stable, searchable unit now (not the whole file being append-only); closing a ticket means filing its narrative under the matching subsystem entry, merging into it if one already covers the same primitive, rather than appending at the end. |
| Examples | `PARSER_LONG_TAIL.md` | Standing strategy + recurring lessons + enumerated worked samples for the indefinite parser tail. Neither backlog nor worklog. |
| Singleton queue | `singletons.md` | Cards confirmed (via `parser_probe.py blocked`) to share their exact gap with no other cached card — real work, but not ticket-worthy on their own. A queue for `hand-author-card`, not a ticket; promote a row into a real ticket the moment a second card is found sharing its shape. |
| Working memory | `workingOn.md` | The resumable state of the ticket **being built right now** — done / in progress / exact next step / decisions / baselines / known red tests, one block per ticket — including a **partly done ticket's residue** (exactly what is still open, and the next step), which lives here rather than in `BACKLOG.md` and keeps the block alive until the residue is done. **Read it first** when starting or resuming ticket work and continue from its *Next step* instead of re-deriving the state; **update it at every milestone** (sub-step built + tested, decision, before a long run or a commit) so a crash, an expired prompt cache or an update loses nothing. On closing the ticket delete its block — only the empty header/template stays (no ticket id, no log). |

(The former `backend/ToDo_Backend.md` and `frontend/ToDo_Frontend.md` are
gone — merged into `BACKLOG.md`.) The plan to finish is
`docs/implementation-state/10_COMPLETION_ROADMAP.md`
(dependency-ordered milestones, reconciling the backlog files above into a
coverage table). `docs/` is organized by *kind of question*: `requirements/`
(what should it do), `concepts/` (how is it designed — architecture, effect
system, oracle parser, plus [PlantUML architecture diagrams](docs/concepts/12_ARCHITECTURE_DIAGRAMS.md)),
`Reference/` (how do I do X, or look something up — card-cache format,
card-catalogue authoring, plus the Comprehensive Rules text + `rules_wiki/`),
`implementation-state/` (what's built now — the roadmap above, both `Done_*`
files, and the original phased `IMPLEMENTATION_GUIDE.md`). See
[docs/README.md](docs/README.md) for the full map. End-user documentation
(how to *use* the app — deck import, Goldfisch, Replay/Puzzle, settings —
not how it's built) lives separately in [`user-docs/`](user-docs/), in
English and German.

### Blitz (MEC-109)

`backend/mtg_analyzer/game/blitz.py` implements RULE 702.152: alternative payments, Henzie grants/discounts, perpetual grants and the next-end-step sacrifice. Casting and legal-action mixins pass a zero-based `blitz` instance index through the session API. `backend/tests/test_blitz.py` covers the lifecycle and costs; Blitz does not inherently exile the creature.

## Conventions & gotchas

- **RULE references**: comment rules-relevant code with the CR number
  (`RULE 613.7`). Match the surrounding comment density and style. To read the
  actual rule text, use the wiki in `docs/Reference/rules_wiki/` — it maps every rule
  number and glossary term to its line in the CR source (too large to load whole);
  regenerate with `build_wiki.py` after a rules update.
- **Model → game import boundary**: `models/` must not import `game/` at module
  load. Where a model needs engine logic (e.g. `GameObject.to_dict` showing
  keywords), use a **function-scoped import** and keep the `game/` side pure of
  runtime model imports (`combat.py`, `continuous.py` only import models under
  `TYPE_CHECKING`).
- **`turn_number` vs `round_number`**: `GameState.turn_number` is the
  rules-correct count (RULE 500.1 — *every* player's turn is a turn, so a
  two-player game is on turn 7 when the starting player takes their
  fourth), and it is what the engine reads everywhere. `round_number` is
  display-only: how often the turn has come back to whoever started, which
  is what a player means by "we're on turn 4". The board shows the round
  and puts the turn in a tooltip. Don't "fix" either one into the other.
- **Derived characteristics**: `GameObject.power/toughness/is_creature/
  granted_keywords` read layer-engine output stamped by `continuous.recompute`,
  falling back to printed+counters when no pass has run. Recompute runs on every
  SBA pass and before the session view — call `engine.recompute_continuous_effects()`
  if you read derived state outside those points.
- **Security**: nothing derived from card text becomes code. Effects are a
  whitelisted `type` string + clamped params (`spec.py`); the binder is the only
  thing that turns specs into behaviour.
- **No magic numbers**: a numeric literal whose meaning isn't obvious from
  its immediate context (a threshold, weight, cap, timeout, percentage,
  scoring constant, …) must be a named module- or class-level constant with
  a short comment stating what it represents — and, when the value is a
  judgment call rather than a rule-derived fact, *why* that value — not
  inlined at the call site. `services/dynamic_analysis.py`'s
  `INFINITE_MANA_THRESHOLD` is the pattern: named, with a comment
  explaining the reasoning behind the exact number. Applies project-wide,
  backend and frontend.
- **Configuration**: on-disk paths and runtime constants (cache/data
  dirs, Scryfall User-Agent/rate limit, multiplayer timers, worker/pool
  sizes) live in `mtg_analyzer/config.py`. Each value resolves with a
  fixed precedence: **`MTG_*` env var > `mtg_analyzer/config.json` >
  built-in default**. The JSON file is committed with every knob written
  out at its default plus a per-section `_comment` (keys starting with
  `_` are ignored); a missing/malformed file is ignored and the server
  still starts. Point elsewhere with `MTG_CONFIG_FILE`. The env vars
  (`MTG_CACHE_DIR`/`MTG_DATA_DIR`/`MTG_USER_AGENT`/
  `MTG_SCRYFALL_MIN_REQUEST_INTERVAL`/…) still work and still win, so a
  one-off script or test run points elsewhere without colliding with a
  real dev server. Service modules (`card_database.py`, `deck_database.py`,
  etc.) keep their old constant names (`CACHE_ROOT`, `DEFAULT_DB_PATH`, …)
  as aliases onto `config.py`'s values; `api/dependencies.py`'s singletons
  import straight from `config.py`.
- **Concurrency / workers**: the backend runs as **one** uvicorn process
  on purpose (`setup/start.py` — the game-session manager, multiplayer
  lobby and dynamic-analysis job registry are in-memory process-wide
  singletons, so `uvicorn --workers N` would split them). Concurrency
  within that process has three configurable knobs (env var / `config.json`
  `[workers]` / `start.sh` flag): `SERVER_THREAD_WORKERS`
  (`--server-threads`, default 40) sizes the AnyIO request-thread pool
  applied in `api/app.py`'s lifespan — every gameplay endpoint is a sync
  `def`, so this is the ceiling on games mid-step at once;
  `DYNAMIC_ANALYSIS_WORKERS` (`--analysis-jobs`, default 4) is an
  admission cap on concurrent analysis *jobs* (`_JobWorkerPool`); and
  `DYNAMIC_ANALYSIS_MATCH_WORKERS` (`--analysis-match-workers`, default 0
  = one per CPU core, 1 = off) is the real speed-up — `run_dynamic_analysis`
  fans one job's independent match simulations across a
  `ProcessPoolExecutor` (GIL-bypassing), falling back to in-process for a
  small job (`_MIN_MATCHES_FOR_PROCESS_POOL`) or if the pool can't start.
- **Logging**: nothing configured logging before, so `mtg_analyzer.*`
  records fell through to `logging.lastResort` (WARNING+ only). `config.
  LOG_LEVEL` (`MTG_LOG_LEVEL` / `config.json` `logging.level` /
  `./start.sh --log <level>`) now sets the `mtg_analyzer` parent logger's
  level, applied in `create_app()` via `_configure_logging()`. Default
  **WARNING** (the engine/parser are chatty at INFO); the root level
  stays WARNING so raising the app to DEBUG doesn't unmute third-party
  libraries. `start.sh --log` passes the same level to uvicorn as
  `--log-level` (whose own default this project overrides to `warning`).
- **Scryfall loading policy** lives in `config.py` too:
  `SCRYFALL_PRIMARY` (`MTG_SCRYFALL_PRIMARY` env var, or
  `./start.sh --scryfall-primary`) — default `False`, **cache-primary**:
  an already-cached card is served as-is even if it looks `stale`
  (missing mana-cost/image data, a pre-fix `Card.partner_with`
  reminder-text tail — see `services/lazy_card_loader.py`'s `_is_fresh`),
  never silently refetched, so an ordinary deck load can't make a
  surprise Scryfall call (or hit its rate limit) just from browsing
  already-known cards. `True` restores this project's original
  **scryfall-primary** behavior of always refetching a stale row. A name
  that's never been cached at all is *always* fetched once either way —
  that part isn't a policy choice.
- **Alternate printing names:** `CardDatabase.get_card` matches canonical
  names, front faces, `flavor_name` and verified `card_aliases`. The loader
  records requested names independently of the selected Scryfall printing;
  saving another printing cannot erase earlier aliases. Aliases point to a
  canonical name, survive a schema reset of card payloads and work again
  after offline reseeding. A previously unknown printing name still needs
  one Scryfall lookup because `oracle_cards` contains one representative
  printing per Oracle card. Deleting the entire disposable cache also
  deletes its aliases. Scripts must pass `DEFAULT_DB_PATH` explicitly:
  `CardDatabase()` alone creates an in-memory database.
- **Frontend**: no framework. Views are `render*(container)` functions setting
  `innerHTML` and wiring listeners; escape user/card text with `escapeHtml` /
  `escapeAttr`. Client-only prefs persist via cookies (`cookies.js`).
- **Commits**: only when asked; branch first if on `main`. End commit messages
  with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Anti-proliferation — keep this file small.** Every session loads it in
  full, so it is orientation only: purpose, run/test commands, invariants that
  must never be violated, conventions and the "Where to look first" table.
  Before adding a line, ask whether an agent working elsewhere needs it
  *every time*; if not, it belongs in `docs/Reference/` (or a folder-local
  `CLAUDE.md`) behind a one-line pointer. Do not create a new `docs/` file for
  something an existing doc already covers (grep first, extend that doc); do not
  duplicate a fact in two places; do not add a new top-level section for one
  feature.
- **Anti-worklog — no "what shipped" narrative here.** A mechanic's delivery
  story ("X now does Y, see test Z"), card names, ticket IDs, coverage numbers
  that change per batch and per-card behaviour do not go in `CLAUDE.md`. They go
  in `Done_Backend.md` / `Done_Frontend.md` (shipped narrative), the card's code
  and tests (per-card behaviour), or `BACKLOG.md` / `workingOn.md` (open work).
  `CLAUDE.md` keeps only the rule or invariant a future change must respect.
  When closing a ticket, do not touch this file unless a convention or
  invariant itself changed.
- **Backlog/worklog split discipline**: `BACKLOG.md` is read in full often
  (by humans and Claude) and, unlike `Done_*.md`, isn't a durable catalogue
  — it holds *only* open work. **Closing a ticket = deleting it from
  `BACKLOG.md`** and filing its narrative into `Done_Backend.md` /
  `Done_Frontend.md`, organized by game-mechanic/app-area rather than by
  date (see each file's own preamble): find the entry for the primitive/
  feature the ticket touched and extend it, or add a new entry under the
  matching subsystem section (e.g. `## Replacement Effects`, `##
  Multiplayer`) if none exists yet — don't just append at the end of the
  file, and don't create a second entry for a primitive that already has
  one. A ticket that closed several cards by combining existing primitives
  (a saved-deck/cube playability push) gets one short entry under `##
  Deck/Cube Playability Batches` instead, naming what closed and pointing
  at the primitive entries it used. Never leave a `[x]`, a "shipped" note,
  or even a "moved to Done_*.md" pointer in `BACKLOG.md`. **If only part of
  a ticket is done, its residue does not go into `BACKLOG.md`**: the backlog
  keeps just the ticket's terse open point (id, title, one-clause scope, no
  "residue" lists, no progress notes), and what is still open — the
  remaining card clusters, blockers, the exact next step — goes into the
  ticket's block in `docs/implementation-state/workingOn.md`, which stays
  until that residue is done. A "small residue batch" ticket (the
  anti-proliferation bundle `BACKLOG.md`'s preamble describes) is an
  ordinary open point and stays in `BACKLOG.md` until a run starts it;
  from then on the same rule applies. Finished detail or residue left in the
  backlog defeats the split and taxes every future read.
- **No half-implementations — close the loop, don't let a deferred item
  silently roll over.** Every batch/session prioritizes by real
  cards-unlocked (correct — see
  `docs/implementation-state/PARSER_LONG_TAIL.md`), but that has a failure
  mode: a modest-yield item never wins
  the "next batch" slot against bigger ones, so it gets deferred a second
  and third time while the ticket describing it goes stale — worse, a
  *later* batch can build the exact primitive an earlier deferred item was
  "blocked on," for an unrelated card, and never loop back to close the
  original entry. Concrete example this bit us on 2026-07-20: Batch 4
  deferred "draw a card at the beginning of the next turn's upkeep" as
  needing "a delayed-trigger phrasing distinct from a standing phase
  trigger"; Batch 22 (2026-07-18) then built exactly that primitive
  (`CreateDelayedTriggerEffect`/`GameState.delayed_triggers`, RULE 603.7)
  for a *different* card (Mana Drain) — and the original ToDo entry was
  never revisited, so it still read as engine-blocked when the real
  remaining gap had shrunk to "write the parser handler." Similarly,
  "grant an activated ability" (Umbral Mantle/Squirrel Nest) was deferred
  as needing a new primitive in Batch 3, confirmed again in Batch 7, and
  is *still* neither built nor hand-authored as the stopgap this repo's
  own escape valve explicitly sanctions (`game/card_catalogue/` — see
  [docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)),
  three rounds of deferral in. To prevent this: (1) before writing "needs a
  new primitive/mechanism" in a `BACKLOG.md` ticket, grep `game/effects.py`/
  `game/rules_engine.py`/`Done_Backend.md` for whether an equivalently-shaped
  primitive already exists from a *different* card's batch — cite it or
  rule it out explicitly, don't assume; (2) whenever a batch **does** build
  a new primitive, grep `BACKLOG.md` for any other ticket the same
  primitive would also close or narrow, and update them in the same pass —
  a primitive landing is exactly the moment to sweep for this, not an
  afterthought; (3) an item deferred a **second** time must either get
  hand-authored as a stopgap in that same batch (the sanctioned escape
  valve — a named blocker cited across 2+ batches is reason enough on its
  own) or be explicitly flagged as promoted to next-up — it must not be
  allowed to silently roll to a third deferral with unchanged wording.

## Where to look first

| Task | Start in |
| --- | --- |
| Playing a card during a resolving effect (RULE 608.2g) | `effects.GameContext.offer_play_during_resolution`, `GameEngine.play_resolution_card` / `resolution_play_actions`, and the matching `services/game_session.py` action/choice path; preserves targets, modes, announced optional life payments, paid/free graveyard casts and land-play limits without a turn-long grant |
| Combat / keywords | `game/combat.py`, `game/game_engine.py` (`_step_combat_damage`) |
| Static abilities / P/T / anthems | `game/continuous.py`, `models/game_object.py` |
| "As long as …" conditions on a static (RULE 613.6) | `game/static_conditions.py` — the project's **single state-predicate vocabulary**, read by statics' `active_if`, trigger intervening-ifs, `binding/core.py`'s replacement gate and (via `game/effect_conditions.py`) resolving effects; includes `opponent_was_dealt_damage_this_turn` (damage per opponent, distinct from life loss); plus `parser/oracle/catalogue/static_handlers.py` (`_STATIC_CONDITION_RES`, `_conditional_static_specs`) |
| "Until …" durations on a continuous effect (RULE 611) | `game/durations.py`, `GameState.floating_statics`, `effects.GrantUntilEffect` — note "until end of turn" stays on the `temp_*` path |
| How many targets a spell/ability wants (RULE 115.1/601.2c) | `game/targeting.py` (`TargetSpec.count`/`count_max`/`count_selector`, `effective_count`, `resolved_count`, `expand_counts`/`collapse_groups`) |
| "Another target land" / "another target land you control" | `game/targeting.py` (`other_land` / `other_land_you_control` exclude the source; ordinary land kinds include it), `parser/oracle/catalogue/subgrammars.py` (`OTHER_TARGET_KINDS`) |
| A clause naming what a previous clause targeted, created, or revealed | `effects.GameContext.previous_targets` / `created_objects` / `revealed_card` (all maintained by `_apply_effects_partitioned`; `revealed_card` is the `of: "revealed"` referent, set by `reveal_top`) |
| "It" / "that creature" under a group trigger ("whenever a creature you control enters …", RULE 603.1) | `game/effects/composition.py`'s `TriggerSubjectReferentEffect` (`trigger_subject_referent`: seeds `previous_targets`, runs a body *against* the firing object, `acting="controller"` for "its controller …", `event_key="remembered"` inside a payment's "if you do"); the parser reaches it from `parser/oracle/catalogue/handlers.py`'s `match_clause` (group fallbacks, tried only after every row written for the group subject), `parser/oracle/catalogue/referent_condition.py` (conditions on "it") and `segmenter._referent_characteristic_specs` / `_hoist_referent_seed`; a bare `it` read as the *source* under a group trigger is wrong-but-MODELED — see the PAR-123 lesson in `PARSER_LONG_TAIL.md` |
| Activated abilities / costs | `game/costs.py`, `game/game_engine.py` (`activate_ability`) |
| Card abilities / fetch lands / enters-tapped | `game/card_catalogue/` (one file per card), `game/card_registry/` (the `register`/`specs_for` mechanism), `effect_binder.bind_from_catalogue` |
| Hand-authoring a specific card's effects | `hand-author-card` skill, [docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md) |
| Effects / triggers | `game/effects.py`, `game/effect_binder.py` |
| Which trigger conditions the parser recognizes | `parser/oracle/segmenter.py` (`_TRIGGER_VERBS` object subjects, `_PHASE_STEP_WORDS`, `_PLAYER_TRIGGER_CONDITIONS` "whenever **you** scry/surveil", `_VARIANT_TRIGGER_CONDITIONS`) |
| Face-down permanents (morph/disguise/manifest/cloak) | `game/face_down.py`, `models/game_object.py` (`turn_face_down`/`turn_face_up`), `game/game_engine.py` (`turn_face_up`, `face="face_down"`) |
| Dungeons + venturing | `models/dungeon.py`, `game/dungeons.py`, `services/dungeon_database.py`, `rules_engine.venture_into_the_dungeon` |
| Formats & casual variants (Planechase/Archenemy/Vanguard) | `models/game_format.py`, `game/variants.py`, `services/variant_card_database.py`, `game_engine.new_game(game_format=…)` |
| "Play/cast from top of library" permission | `game/top_library.py`, `game/game_engine.py` (`can_play_land`/`can_cast`/`legal_actions`), `gameBoardView.js` (`libraryTopHtml`) |
| Who an effect acts on / how much it measures (an operand naming a referent) | `backend/mtg_analyzer/game/effect_operands.py` (`{"of": …, "as": "controller"}`), `game/effect_amounts.py`; both resolve referents through `effect_conditions.subject_of` |
| Combining effects: branching, "you may", "for each", "…equal to" | `backend/mtg_analyzer/game/effects/composition.py` (`seq`/`if_else`/`optional`/`for_each`/`bind`), `game/effect_amounts.py` (what `bind` measures) |
| An "if `<predicate>`, `<effect>`" gate on a resolving effect (RULE 603.4/702.33b) | `backend/mtg_analyzer/game/effect_conditions.py` (referents + the `GameContext` predicates + the flat-key translator), `game/static_conditions.py` (every state predicate, shared with statics/triggers/replacements), `parser/oracle/segmenter.py`'s `_CONDITION_PREFIXES` |
| A player choice: opening one, answering one, adding a new kind | `backend/mtg_analyzer/game/continuations.py` (the handler registry), `RulesEngine.open_choice`/`resolve_choice` |
| What an effect type/engine method *is* (instruction/fusion/alias/…) | `backend/mtg_analyzer/game/isa.py`, `scripts/isa_report.py --registry` |
| Which operations the corpus actually uses, and their argument frames | `scripts/isa_report.py --corpus` (re-derives `13_` §5.6b from the ledger) |
| What a `TargetSpec.kind` decomposes into (types × scope × filters) | `game/targeting.py`'s `TARGET_FRAMES` |
| Mana abilities with “Activate only if …” (Mox Opal / Metalcraft) | `game/mana_abilities.py` parses the shared activation condition and gates production options; `engine/activation_mixin.py` rechecks it during cost validation, including mana abilities and auto-tap |
| On-disk paths / env-var config | `backend/mtg_analyzer/config.py` |
| Goldfish UI | `frontend/src/js/goldfishView.js` |
| Solo vs. bots (Multiplayer engine, no lobby) | `backend/mtg_analyzer/api/solo.py`, `frontend/src/js/soloView.js`; shared picker/mulligan/banner markup in `frontend/src/js/gameSetup.js` (also used by goldfish/multiplayer) |
| Multiplayer (lobby, seats, shared board) | `backend/mtg_analyzer/services/lobby.py`, `api/multiplayer.py`, `api/multiplayer_ws.py`, `frontend/src/js/multiplayerView.js`, `lobbySocket.js`, `bannerColors.js` (seat banner colours) |
| Bots filling a multiplayer seat (UC5) | `backend/mtg_analyzer/services/bots.py` (registry/driver, compatible class exports; individual policies in `services/bot_policies/`, deck planning in `services/bot_strategy.py`), `services/lobby.py` (`Seat.bot_kind`, `add_bot`), `frontend/src/js/multiplayerView.js` (`addBotHtml`/`seatRowHtml`) |
| Replay/Puzzle mode (build+save/load a board) | `backend/mtg_analyzer/services/replay.py`, `game_session.py` (`edit_*` actions), `frontend/src/js/replayView.js` |
| Archidekt deck import proxy | `backend/mtg_analyzer/services/archidekt_client.py`, `api/import_external.py` (Moxfield was tried and reverted twice — Cloudflare-blocked; don't re-add it without checking that's changed) |
| Refreshing the full Oracle card pool (new set) | `backend/scripts/update_card_pool.py` — re-downloads the Scryfall `oracle_cards` bulk dump, merges it into `RawCardStore`, reseeds the app cache, and prints a ban-list drift heads-up (`scripts/import_bulk.py` is first-load only; its default reuses an on-disk dump) |
| Commander Spellbook combo snapshot, lazy matching, and Bracket signals | `backend/mtg_analyzer/services/commander_spellbook_database.py`, `api/combos.py`, `frontend/src/js/analyzeView.js`, `deckAnalysis.js`; full data contract, DB lifecycle, matching limits, and the narrow infinite-combo heuristic in [docs/Reference/COMMANDER_SPELLBOOK.md](docs/Reference/COMMANDER_SPELLBOOK.md) |
| Applying a ban-list update | `backend/scripts/update_ban_lists.py` — rewrites a hand-maintained ban-list constant (`BAN_LIST_TARGETS`, just `services/commander_legality.py`'s `BANNED_COMMANDER_CARDS` today) straight from the raw store's live `legalities` data; no network of its own, run `update_card_pool.py` first. `--format <key>`/`--dry-run` |
| Player-uploaded token art / card-back sleeves | `backend/mtg_analyzer/services/player_assets.py`, `api/player_assets.py`, `frontend/src/js/profileView.js` (upload UI + player name), `gameBoardView.js` (`resolveImageUrl`/`setAssets`) |
| Default art for a vanilla ("1/1 white Soldier") token | `backend/mtg_analyzer/services/token_database.py` (`TokenArtLibrary`, keyed by exact name/power/toughness/colors — a token name is reprinted at multiple stat lines across sets), `data/token_art.json`, `scripts/build_token_art_library.py` (rebuild from a fresh Scryfall bulk dump); consumed by `synthesize_token_card` and `services/replay.py`'s `_token_card` |
| Engine coverage doc (user-facing) | `frontend/src/js/implementationStatusView.js` |
| Resuming a ticket someone (or a crashed session) was building | [docs/implementation-state/workingOn.md](docs/implementation-state/workingOn.md) — its block's *Next step*; update it as you go, delete the block on close |
| What's still open (any area) | [docs/implementation-state/BACKLOG.md](docs/implementation-state/BACKLOG.md) — tickets by category; parked/low-priority + non-goals in [DEFERRED.md](docs/implementation-state/DEFERRED.md) |
| Why shipped work looks the way it does | [Done_Backend.md](docs/implementation-state/Done_Backend.md) / [Done_Frontend.md](docs/implementation-state/Done_Frontend.md) |
| Parser-tail strategy, lessons, worked samples | [docs/implementation-state/PARSER_LONG_TAIL.md](docs/implementation-state/PARSER_LONG_TAIL.md) |
| Looking up a `RULE <n>` in the CR text | `docs/Reference/rules_wiki/` (rule#/term → source line; see its `README.md`) |
| Full docs/ map (requirements/concepts/Reference/implementation-state) | [docs/README.md](docs/README.md) |
| How to *use* the app (not build it) | [user-docs/](user-docs/) (English + German) |

## Local bug reports

The bug icon beside Settings opens a report dialog; `POST /api/bug-reports` saves
gzip JSON in the Git-ignored `bug-reports/` (never commit or delete them without an
explicit request; they contain hidden zones). To analyze one, read
[docs/Reference/BUG_REPORTS.md](docs/Reference/BUG_REPORTS.md) first.
