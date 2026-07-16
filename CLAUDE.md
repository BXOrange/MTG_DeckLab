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
  deck import/analysis, saved decks, the goldfish board, the **"Replay"**
  board editor (a.k.a. puzzle mode), the card cache, a Multiplayer stub, and
  an **"Engine-Status"** tab documenting engine coverage, plus two header icon
  buttons: **"Einstellungen"** (server address, player-uploaded token art,
  card-back sleeves) and **"Profil"** (`profileView.js` — just the player
  name, split out of Einstellungen so it reads as "who you are" rather than
  a connection setting). UI language is **German**; MTG keyword names stay
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
`GET /api/game/{id}/replay-export` works for a goldfish session too, so a
goldfish position can be exported and re-opened in Replay. Frontend:
`frontend/src/js/replayView.js`.

**Player-uploaded art** (Einstellungen tab): a player can upload art for
tokens that have no real Scryfall art (matched by token name) and a
library of card-back "sleeve" designs, one of which can be picked per
saved deck (`Deck.sleeve_id`). Stored server-side keyed by the free-text
player name (this app has no auth) — set on the **Profil** tab
(`profileView.js`), read via `getSettings().playerName` — via `services/
player_assets.py` / `api/player_assets.py` rather than client-side,
specifically so a shared backend can serve them to an opponent too, once
multiplayer (`POST /api/game/multiplayer` is still a 501 stub) exists.
The goldfish/Replay board (`gameBoardView.js` `resolveImageUrl`) renders
a token's uploaded art when present, and falls back to the active
sleeve for a face-down/transformed token with none — real transformed
DFCs keep their genuine Scryfall back-face art, so the sleeve fallback
has no visible effect yet until a face-down permanent state
(morph/manifest, not yet modeled) can reach that branch.

A saved `Deck` also carries a free-text, optional `author` field (a
descriptive credit, not an owner/auth concept — this app still has no user
accounts) — set on the deck-import/edit tab and shown read-only in the
saved-decks list, preserved-on-omission the same way `sleeve_id` is
(`api/saved_decks.py`'s `save_deck`: a re-save that doesn't send `author`
keeps the existing value). The saved-decks list also gained client-side
color-identity/legality filters, the same checkbox-fieldset pattern the
card cache view uses (`savedDecksView.js`/`cachedCardsView.js`).

## Run & test

```bash
# Full app (frontend static server on http://localhost:8765; sets up backend venv)
./start.sh                     # add --backend-tests to also run pytest

# Backend tests directly (do this after any backend change)
cd backend && python -m pytest -q
# or: source backend/venv/bin/activate && pytest backend/tests/
```

The backend FastAPI app is `mtg_analyzer.api.app:app`. There is **no JS build
step** and no Node toolchain — edit `frontend/src/**` and reload. There is no
JS test runner, so validate frontend changes by reasoning + reading; validate
backend changes with pytest (the suite is fast, ~500+ tests, keep it green).

## Architecture & data flow

```
Card (models/card.py)            immutable printed characteristics
  └─ GameObject (models/game_object.py)   one instance in a zone, mutable state
GameState (models/game_state.py)  battlefield/stack/players/turn + event bus
RulesEngine (game/rules_engine.py) rules primitives: cast, damage, draw, SBAs…
GameEngine  (game/game_engine.py)  turn/phase loop, actions, legal_actions, combat
GameSession (services/game_session.py) wraps an engine: snapshots/undo, wire view
API (api/game.py)  ── JSON ──▶  frontend (src/js/goldfishView.js)
```

Oracle-text → behaviour pipeline (docs/09):
`AbilitySpec` IR (`parser/oracle/spec.py`, pure JSON-shaped data, the security
boundary) → **binder** (`game/effect_binder.py`) → live `GameEffect` objects via
the `EffectRegistry` (`game/effects.py`). **Bind-on-load** is wired:
`build_goldfish_engine` calls `bind_from_catalogue(obj)` for every object it
creates, sourcing specs from `game/ability_catalogue.py` (a hand-authored,
name-keyed registry — e.g. Evolving Wilds' fetch) **and** the oracle-text
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
  + oracle text) and the rules they impose (blocking legality, damage steps).
- `continuous.py` — the **RULE 613 layer engine**. `recompute(state)` re-derives
  every battlefield permanent's characteristics in layer order and stamps
  derived P/T, types, granted keywords + a per-object `static_trace`.
- `costs.py` — regex parser for **activated-ability costs** (`Cost: Effect`).
- `ability_catalogue.py` — card→`AbilitySpec` registry (bind-on-load source),
  now also falling back to the oracle-text parser (`parser/oracle/gate.parse_oracle`)
  for unregistered `MODELED` cards + `enters_tapped` (RULE 614.1, oracle-derived).
- `targeting.py` — legal-target computation (RULE 115 / 601.2c).
- `mana_abilities.py`, `models/mana_cost.py`, `models/mana_pool.py` — mana.

## Implementation state (summary)

The user-facing detail lives in the frontend **Engine-Status tab**
(`frontend/src/js/implementationStatusView.js`) — keep that file in sync when
the engine gains/loses coverage. This section is a short orientation only —
for the actual mechanic-by-mechanic detail (what shipped, *why* it was built
that way, which tests cover it), read
[docs/implementation-state/Done_Backend.md](docs/implementation-state/Done_Backend.md);
for open gaps and exactly what's left on a partial feature, read
`backend/ToDo_Backend.md`. Both are organized under the same section headers
(Rules Engine, Game Engine, Card-type & structural coverage, …) — search
those files for a mechanic's name rather than re-deriving its state from the
code or duplicating detail here.

**Implemented**: the full turn/stack/priority/SBA loop; London mulligan;
targeting; the whole mana model (generic/color/colorless/hybrid/mono-hybrid/
Phyrexian/{X}), including RULE 605.3a **spend restrictions** ("Spend this
mana only to cast a creature spell") as tagged lots in `models/mana_pool.py`
gated by a caller-supplied predicate (`game/mana_abilities.py`'s
`restriction_predicate_for_cast`/`_for_activation`), RULE 605.1a "any
combination of colors" mana (`ManaAbility.any_combination`,
`GameEngine.tap_for_mana`'s `color_split`), and RULE 605.1a hand-zone mana
abilities ("Exile this card from your hand: Add …", Elvish/Simian Spirit
Guide — `hand_mana_abilities_for`/`GameEngine.activate_hand_mana_ability`);
all common combat keywords incl. landwalk; the RULE 613
**layer system** (layers 1–7, timestamp-ordered within a layer + a bounded
RULE 613.8 dependency pass, `EffectRegistry`-bridged for every hand-authored/
parsed `static` spec shape, including layer-6 grants of a non-keyword mana
or triggered ability and `affects="attached_permanent"` for Auras/Equipment/
Reconfigure); Aura/Equipment/Fortify/Reconfigure attachment; activated
abilities incl. loyalty `[±N]` costs; triggered abilities + RULE 616
replacement effects, both with **interactive ordering** when 2+ apply to the
same event/trigger batch, and a triggered ability's own target/"you may"
chosen interactively too; the one-shot effect library (damage/draw/discard/
destroy/counter/search/gain_life/mill/exile/tap/counters/pump/scry/
create-token/copy_permanent/become_copy/cascade/discover/…); tokens (RULE
704.5d lifecycle); planeswalkers; commander damage + tax; the full RULE 702
keyword catalogue (194 keywords, flag keywords bound to combat); and the
deeper card-type structures — DFC transform + day/night/daybound-nightbound,
modal-DFC/Adventure/Split-Fuse/Prepared casting, Saga chapters, Class/Leveler
level-ups.

The **oracle-text → behaviour parser** (docs/09, `parser/oracle/`) is the
main ongoing effort: `normalize` → `segmenter` → `catalogue/handlers` →
`gate.parse_oracle` turns oracle text into `AbilitySpec`s with a fail-closed
`MODELED`/`UNMODELED` coverage verdict (a card only gets parsed effects when
*fully* modeled — never half-resolved). It covers most one-shot effect
families, ETB/dies/attacks/blocks/Saga-chapter triggers with RULE 603.1
subject scoping, `<cost>: <effect>` activated abilities, modal spells (both
spell-level and, since 2026-07-16, triggered-ability-level "choose one —"),
additional cast costs, the counter family, RULE 614.1 enters-tapped clauses
(all four conditional variants) and enters-with-N-counters clauses, static
anthem/lord clauses, and graveyard-card recursion/exile (Regrowth/
Reanimate/Deathrite Shaman-shaped — own/any/an opponent's graveyard × any
card type); regenerate (RULE 701.16 — a new pre-emptively-fired
`EventType.DESTROY` `RulesEngine.destroy` runs through the existing
replacement-effect machinery so `RulesEngine.regenerate`'s shield can
intercept it; also closed a RULE 701.16c gap where sacrifice previously
went through `destroy` too and could have wrongly been save-able by a
shield — sacrifice now uses the new non-destructive
`RulesEngine.put_into_graveyard`); RULE 115.1a "up to one target" (any
`{TARGET}`-based handler, N=1 only — a real N>=2 multi-target choice is a
separate, larger unshipped feature); RULE 702.33b's "if this spell was
kicked, \<effect\>." as an *additional* effect (`EffectSpec.condition` +
`game/effects.py`'s `ConditionalEffect`, not the "if kicked, ... instead"
amount-override shape); oracle-text recognition of 3 of the 5
already-bound replacement families (`double_tokens`/`double_counters`/
`additional_damage` — standing-permanent clauses; `prevent_damage`'s
two real cards are a different, still-unmodeled one-shot-spell shape);
and surveil (RULE 701.31, mirroring the existing scry handler/effect
shape exactly). `parse_oracle` itself is now memoized (content-keyed on
every field it reads, `parser/oracle/gate.py`) since it's called once per
`GameObject` built — a popular card no longer gets re-parsed from scratch
on every copy/every game. `parser/oracle/processing_list.py` tracks
cache-wide coverage (21.4% of the 2,869-card cache fully `MODELED` as of
2026-07-16 — re-run `coverage_over_cards()` before trusting this number,
the cache grows) and ranks the next handlers worth building.

**Notable gaps** (see `backend/ToDo_Backend.md` for the full list with exact
scope on each): a real N>=2 "up to N target(s)" multi-select; a "remove a
counter from ~" activation-cost shape (`costs.py`); a kicked spell's "if
kicked, ... instead" *override* conditional (as opposed to the additional-
effect shape already shipped); the remaining RULE 616.1 replacement-clause
formulations (`prevent_damage`'s one-shot-spell shape, differently-scoped/
compound-filter variants); wiring the interactive priority primitive
into the multiplayer session/WebSocket; and battles/dungeons. Narrower,
already-shipped-feature rough edges
(e.g. re-validating an *existing* attachment's legality every SBA pass, not
just on the host leaving; combining interactive trigger-ordering with a
targeted trigger; bespoke *conditional* transform triggers like Delver of
Secrets) are tracked separately in
[docs/implementation-state/ToDo_EdgeCases.md](docs/implementation-state/ToDo_EdgeCases.md).

Hand-authoring a card's abilities directly (rather than waiting on the
oracle-effect front-end, or for a replacement-clause/conditional-trigger the
front-end can't express yet) goes in `game/ability_catalogue.py` — see
[docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)
for the field-by-field how-to and the full `EffectSpec`/layer whitelist.

Living backlogs: `backend/ToDo_Backend.md` (open, stays next to the backend
code it tracks) and `docs/implementation-state/Done_Backend.md` (shipped —
append-only history rather than something edited in lockstep with
in-progress code, so it lives under `docs/`; same split for the frontend's
`frontend/ToDo_Frontend.md` / `docs/implementation-state/Done_Frontend.md`).
[`docs/implementation-state/ToDo_EdgeCases.md`](docs/implementation-state/ToDo_EdgeCases.md)
is a narrower, cross-cutting sibling: specific, low-probability scenarios a
shipped feature deliberately leaves unhandled (not a large open feature —
those stay in the ToDo files above) — check it before treating one of these
as a surprise bug. The plan to finish is `docs/implementation-state/10_COMPLETION_ROADMAP.md`
(dependency-ordered milestones, reconciling the backlog files above into a
coverage table). `docs/` is organized by *kind of question*: `requirements/`
(what should it do), `concepts/` (how is it designed — architecture, effect
system, oracle parser, plus [PlantUML architecture diagrams](docs/concepts/12_ARCHITECTURE_DIAGRAMS.md)),
`Reference/` (how do I do X, or look something up — card-cache format,
card-catalogue authoring, plus the Comprehensive Rules text + `rules_wiki/`),
`implementation-state/` (what's built now — the roadmap above, both `Done_*`
files, the original phased `IMPLEMENTATION_GUIDE.md`, and the archived
Weeks 1–4 status log at `implementation-state/history/IMPLEMENTATION_STATUS.md`).
See
[docs/README.md](docs/README.md) for the full map. End-user documentation
(how to *use* the app — deck import, Goldfisch, Replay/Puzzle, settings —
not how it's built) lives separately in [`user-docs/`](user-docs/), in
English and German.

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
- **Derived characteristics**: `GameObject.power/toughness/is_creature/
  granted_keywords` read layer-engine output stamped by `continuous.recompute`,
  falling back to printed+counters when no pass has run. Recompute runs on every
  SBA pass and before the session view — call `engine.recompute_continuous_effects()`
  if you read derived state outside those points.
- **Security**: nothing derived from card text becomes code. Effects are a
  whitelisted `type` string + clamped params (`spec.py`); the binder is the only
  thing that turns specs into behaviour.
- **Configuration**: on-disk paths and a few runtime constants (cache/data
  dirs, Scryfall User-Agent/rate limit) live in `mtg_analyzer/config.py`,
  overridable via `MTG_CACHE_DIR`/`MTG_DATA_DIR`/`MTG_USER_AGENT`/
  `MTG_SCRYFALL_MIN_REQUEST_INTERVAL` env vars — point a one-off script or
  test run elsewhere without colliding with a real dev server's cache/saved
  decks. Service modules (`card_database.py`, `deck_database.py`, etc.) keep
  their old constant names (`CACHE_ROOT`, `DEFAULT_DB_PATH`, …) as aliases
  onto `config.py`'s values; `api/dependencies.py`'s singletons import
  straight from `config.py`. `LazyCardLoader`'s loading *policy* is also
  here: `SCRYFALL_PRIMARY` (`MTG_SCRYFALL_PRIMARY` env var, or
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
- **Frontend**: no framework. Views are `render*(container)` functions setting
  `innerHTML` and wiring listeners; escape user/card text with `escapeHtml` /
  `escapeAttr`. Client-only prefs persist via cookies (`cookies.js`).
- **Commits**: only when asked; branch first if on `main`. End commit messages
  with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **ToDo/Done split discipline**: `backend/ToDo_Backend.md` /
  `frontend/ToDo_Frontend.md` are read in full often (by humans and Claude)
  and, unlike `Done_*.md`, aren't append-only history — they're meant to
  hold *only* open work. When you finish an item, move its narrative into
  the matching section of `docs/implementation-state/Done_Backend.md` /
  `Done_Frontend.md` (section headers mirror 1:1) instead of leaving it
  checked off with its writeup still in place — a one-line "moved to
  Done_*.md, section name" pointer, or just deleting the line, is enough.
  Leaving finished work's full detail sitting in ToDo defeats the split and
  makes every future read of that file more expensive for no reason.

## Where to look first

| Task | Start in |
| --- | --- |
| Combat / keywords | `game/combat.py`, `game/game_engine.py` (`_step_combat_damage`) |
| Static abilities / P/T / anthems | `game/continuous.py`, `models/game_object.py` |
| Activated abilities / costs | `game/costs.py`, `game/game_engine.py` (`activate_ability`) |
| Card abilities / fetch lands / enters-tapped | `game/ability_catalogue.py`, `effect_binder.bind_from_catalogue` |
| Hand-authoring a specific card's effects | [docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md) |
| Effects / triggers | `game/effects.py`, `game/effect_binder.py` |
| On-disk paths / env-var config | `backend/mtg_analyzer/config.py` |
| Goldfish UI | `frontend/src/js/goldfishView.js` |
| Replay/Puzzle mode (build+save/load a board) | `backend/mtg_analyzer/services/replay.py`, `game_session.py` (`edit_*` actions), `frontend/src/js/replayView.js` |
| Archidekt deck import proxy | `backend/mtg_analyzer/services/archidekt_client.py`, `api/import_external.py` (Moxfield was tried and reverted twice — Cloudflare-blocked; don't re-add it without checking that's changed) |
| Player-uploaded token art / card-back sleeves | `backend/mtg_analyzer/services/player_assets.py`, `api/player_assets.py`, `frontend/src/js/connectionSettingsView.js`, `frontend/src/js/profileView.js` (player name), `gameBoardView.js` (`resolveImageUrl`/`setAssets`) |
| Engine coverage doc (user-facing) | `frontend/src/js/implementationStatusView.js` |
| Looking up a `RULE <n>` in the CR text | `docs/Reference/rules_wiki/` (rule#/term → source line; see its `README.md`) |
| Full docs/ map (requirements/concepts/Reference/implementation-state) | [docs/README.md](docs/README.md) |
| How to *use* the app (not build it) | [user-docs/](user-docs/) (English + German) |
