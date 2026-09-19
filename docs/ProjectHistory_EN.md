# DeckLab — Project History

## Origin: "Can I Test My Deck in a Sandbox?"

Magic: The Gathering is a game with over 30 years of rules, edge cases, and mechanics that don't fit in a human head. With over 30,000 different cards, there are infinite combinations.

The original question was simple: **How do I test a Commander deck without playing against real opponents? How do I validate that a combo chain actually works the way I understand it?**

DeckLab began as an internal sandbox mode — called "goldfish" because you play your deck against a passive opponent who takes no actions. The name comes from the MTG community, and the metaphor is apt: you should at least win against a fish.

## Phase 1: Core Infrastructure (July–August 2026)

The first commits show the classic bootstrapping sequence:

1. **Frontend Layout & Deck Import** – A clean German interface for entering decklist text
2. **Card Database** – A local SQLite cache with Scryfall integration to avoid hammering the API constantly
3. **Deck Storage** – Persist saved decks and retrieve them
4. **Basic Game Engine** – The first gameplay loop attempts

Key insights from this phase:

- **Offline-first**: The project should start without internet. The cache should self-heal. Later, this became a central principle: `pip --no-index` for the venv, local database, Scryfall caching with self-healing mechanisms.
- **Separation of Concerns**: Frontend (JavaScript, no build step, buildless ES modules), Backend (Python FastAPI), clear API boundaries.
- **Decklist Parser**: Available on both sides (frontend + backend) to avoid redundancy.

## Phase 2: Game Engine Foundation (July–August 2026)

The real challenge began: **implementing the Comprehensive Rules.**

The MTG rulebook is not just large—it's also tricky:

- **The Mana Pool** — a completely separate accounting system: hybrid mana, Phyrexian mana, color restrictions (RULE 605), "any combination of colors"
- **Combat** — about 30 different evasion keywords, blocking restrictions, complex damage assignment
- **The Stack** — not just "a list of things," but a state machine with Priority (RULE 117), trigger limitations, resolution
- **Permanents with State** — Tap/Untap, counters, transformation (DFCs), levels

Breakthroughs from this phase:

1. **Token Handling** — Cards can create tokens during play. These aren't real Cards, but GameObject instances. The token-database approach (via Scryfall) became standard later.

2. **Layer System (RULE 613)** — A conceptual turning point. Instead of applying effects "in any order," they resolve into 7 numbered layers: here addition, subtraction, type changes, and control transfers happen—in this exact order, always, regardless of the order effects were applied. This is why the engine works at all.

3. **Effect Binding** — A GameEffect is not a string or tree. It's a typed object with parameters: `{"type": "deal_damage", "amount": 3, "recipient": "target"}`. An `EffectRegistry` maps type strings to Python classes. An `AbilitySpec` is pure data (JSON-compatible)—the security boundary between oracle text and executed code.

4. **Ability Catalogue** — Instead of parsing every card, you could just hand-write the abilities. This approach later became the fallback strategy when the parser couldn't handle everything—but initially, you needed *some* playable cards.

## Phase 3: Parser Foundation (August 2026)

The parser is Magic's biggest problem. Every card has oracle text in English. This text is half-regulated, half prose art. The rules are consistent (with ~500 subordinate exceptions), but the syntax is not context-free.

Examples:
- "Whenever you cast a spell, draw a card." — Condition, effect
- "Whenever a creature you control enters, put a +1/+1 counter on another target creature." — Condition, scope ("you control"), effect with targeting
- "Exile the top card of your library. You may play it this turn." — Sequence of effects, with optional continuation

The parser was built in phases:

1. **normalize**: Unify notation. "{T}" becomes "Tap". "and/or" becomes "or".
2. **segmenter**: Break text into sentences and clauses. Recognize trigger conditions ("Whenever..."), costs, effect bodies.
3. **catalogue/handlers**: Each effect type has a handler. "Deal X damage" maps to a `DealDamageEffect` spec.
4. **gate.parse_oracle**: The main gate. Returns `AbilitySpec` lists or `UNMODELED` if something doesn't fit.

Critical insights:

- **Fail-closed is better than half-baked**: A card is only marked `MODELED` if *every* clause is recognized. This means: many cards are `UNMODELED`, but those that are `MODELED` actually work correctly.
- **Pattern matching is hard**: A "lizard with power 2 or less enters" is syntactically completely different from "a lizard enters." Instead of writing one monolithic grammar, it's smarter to have atomic pieces and compose them.
- **Metrics are critical**: How many cards are `MODELED`? Measure again with `parser_probe.py` after each change, don't guess.

## Phase 4: Complex Card Structures (August 2026)

With a working parser and a working engine came the difficult card types:

- **Double-Faced Cards (DFCs)**: A card can have two sides. "Liliana, Waker of the Dead // Liliana's Mastery". The engine needed `front_face`/`back_face` distinction and transform mechanics.
- **Sagas**: A special permanent category with lore counters and chapter-like triggers. RULE 715 has its own resolution rules.
- **Adventures**: A spell with two sides — you can cast the spell or send an adventure, which immediately puts the card into the graveyard.
- **Replacement Effects**: "If X happens, do Y instead." These are **not** triggered abilities — they change what happens before normal effect resolution even starts.

## Phase 5: Replay/Puzzle Mode & Board Construction (August 2026)

Before tackling multiplayer, a different kind of problem emerged: **What if you want to test a specific board state without playing from turn 1?**

Replay/Puzzle mode (internally called "Replay," UI calls it "Puzzle Mode") is a completely different session type:

- **Arbitrary Board Construction**: Instead of playing a legal deck from turn 1, you construct any board state you want. Add creatures, artifacts, enchantments in any position. Set life totals, mana pools, counters.
- **Two-Player Setup**: 1 player = pure puzzle. 2 players = with an opponent.
- **Full Edit API**: `edit_*` actions mutate state directly: add/remove/move objects+tokens, tap, flip, counters, life, poison, player counters, turn markers, phase.
- **Save/Load as JSON**: Export a board state as a re-resolvable descriptor. Cards are identified by name/id, tokens carry self-describing blocks. Import it back later to resume.
- **Same Engine, Different Semantics**: Replay uses the exact same `GameSession`/`GameEngine` as goldfish, just with `mode="replay"` and `require_setup=False`. The engine doesn't know the difference—it's a session configuration.

**Why This Matters for Deck Testing:**

Replay is the sibling to Goldfish. If you're testing whether a specific combo works starting from turn 5, you don't want to play 4 turns of setup. You construct the board, place the key pieces, and verify the sequence. A goldfished board position can be exported to Replay, modified, and re-tested.

This became essential for:
- Verifying complex game states without full playthrough
- Testing edge cases (what if I have 3 Elves out and draw a Growth Spurt?)
- Building reference positions for debugging

## Phase 5b: Multiplayer & Sessions (August–September 2026)

After goldfish and Replay worked, came the big question: **What about real PvP?**

Multiplayer is not just "play with more than 2 players." It's a completely different category:

- **Lobby**: Players join a table. Not authenticated (this project has no user accounts), but with a `client_token` for browser session continuity.
- **Presence & Reconnects** (RULE 104.3a): If a player disconnects, they don't immediately lose the game. There's a 90-second grace period. During that time, priority is passed automatically.
- **Priority (RULE 117)**: The real problem. In solo, the stack runs automatically. In multiplayer, the stack pauses after a spell/ability goes on it. The active player has priority. If they pass, priority goes to the next player. Everyone passes = stack resolves one card. **This is interactive and must work in real-time.**
- **WebSockets**: REST isn't fast enough. One WebSocket connection per player per game, bidirectionally broadcasting board updates.
- **Bots**: "Solo gegen Bots" (UC5 — Use Case 5). A real multiplayer table filled with AI players. A GoldfishBot (plays only lands, passes otherwise) was quick. A GreedyBot (plays everything) was quicker.

Most important discovery from this phase: **The engine doesn't need a multiplayer concept. It only needs per-action actor IDs and per-view-request perspective filters.** Everything else is lobby bookkeeping.

## Phase 6: Massive Parser Batches & ENG-37 (August–September 2026)

Parallel to multiplayer and analysis engine development, came a silent architecture refactoring: **ENG-37 — Fusion Retirement**.

The problem: In the oracle-text parser, there were "fusions" — effect combinations that needed a new, special class. "Draw a card, then discard a card" was a fusion. "Create a token and grant it a keyword" was a fusion. With hundreds of these, code quickly became unreadable.

The insight: **Instead of writing fusions, write atomic primitives and combine them with a composition language.**

ENG-37 was a 6-week refactoring that reduced the entire effect catalog to `seq` (sequence), `if_else` (conditionals), `optional` (you may), `for_each` (repetition), and `bind` (compute a value and substitute). No more fusions. The code shrank by 50%. Test coverage rose.

**Lessons from ENG-37:**
1. Small, testable units beat monolithic "clever" solutions.
2. A composition language is cheaper than hundreds of specialized classes.
3. Measurements of "how many cards work now" should happen before and after major refactorings.

## Phase 6a: Static & Dynamic Deck Analysis (August–September 2026)

Deck analysis has two layers:

**Static Analysis** (immediate, no simulation):
- **Decklist Parsing**: Server-side text parser stripping foil markers, tag/set suffixes, validating structural commands (main/sideboard/commander).
- **Commander Legality**: Real legality checking — color identity (union of all commanders' identity vs. every card), ban list, RULE 903.3 legendary eligibility, all partnership families (plain Partner, "Partner with X", Friends Forever, "Choose a Background").
- **Coverage Assessment**: Which cards are MODELED vs. UNMODELED. Per-deck cache (keyed on `PARSER_VERSION` + catalogue fingerprint) to avoid re-scanning.
- **Mana Curve Analysis**: Per-color distribution, generic pips, color intensity.

**Dynamic Analysis** (simulated):
- **Game Simulation**: Run N independent matches (configurable, default: 8) against the same engine with shuffled random seeds, capturing opening hands and first few turns.
- **Process Pool Parallelization**: Each match is CPU-bound and independent, so simulations fan across a `ProcessPoolExecutor` for real speedup (~3x on a 10-core box). Falls back gracefully to in-process for small jobs.
- **Concurrency Configuration**: Server-wide knob (`DYNAMIC_ANALYSIS_WORKERS`) caps concurrent jobs; per-job worker pool (`DYNAMIC_ANALYSIS_MATCH_WORKERS`, default = CPU core count) sizes the simulation parallelism.
- **Metrics Capture**: Opening-hand quality, first-turn land drop rate, turn-to-first-spell, actual mana curve validation. Returns structured data rather than prose — frontend can present however it wants.

Why both matter: Static analysis answers "is this deck legal?" Dynamic analysis answers "does this deck actually work?"

## Phase 6b: Dynamic Analysis Engine (August–September 2026)

In parallel with the other game modes, came **dynamic deck analysis** — statistical deck evaluation beyond simple card counting and mana curve.

- **Game Simulation**: Run N independent matches (configurable, default: 8) against the same engine with shuffled random seeds, capturing opening hands and first few turns.
- **Process Pool Parallelization**: Each match is CPU-bound and independent, so simulations fan across a `ProcessPoolExecutor` for real speedup (~3x on a 10-core box). Falls back gracefully to in-process for small jobs or if the pool can't start.
- **Concurrency Configuration**: Server-wide knob (`DYNAMIC_ANALYSIS_WORKERS`) caps concurrent jobs; per-job worker pool (`DYNAMIC_ANALYSIS_MATCH_WORKERS`, default = CPU core count) sizes the simulation parallelism.
- **Metrics Capture**: Aggregates opening-hand quality, first-turn land drop rate, turn-to-first-spell, mana curve analysis. Returns structured data rather than prose — the frontend can present it however.

Why this matters: "My deck has 40% lands, good mana curve" tells you nothing about whether it actually *draws* lands when it needs them. A deck with 36 lands and no card draw can still mulligan into oblivion. Simulated games answer real questions.

## Phase 7: Commander-Focused Sprint + Analysis Refinement (September 2026)

Since early September 2026, the focus has been on **Commander legality** and real Commander decks. The project has actual saved decks, and several are 99-card Commander decks from the active cEDH meta.

With four features now available—Goldfish for linear play, **Replay for targeted testing and board construction**, Multiplayer for interactive games, and **Dynamic Analysis for statistical deck evaluation**—the testing surface became comprehensive.

Discoveries:

1. **Replay Mode for Deckbuilding**: Testing a combo-heavy deck meant exporting a goldfish position where the combo was setup-ready, switching to Replay mode, and tweaking the board to verify edge cases. "What if I have exactly 3 Elves? What if the opponent controls a Stony Silence?" Replay answers these instantly.

2. **Complex Mana Lands**: Filter lands like Twilight Mire that produce "Add {B}{B}, {B}{G}, or {G}{G}" were impossible for the auto-tap engine. A new `find_tap_plan` with converter simulation was needed.

3. **Hand-Author-Card Skill**: Not everything the parser can hit. For real one-card gaps (e.g., a card nobody else has), it's faster to hand-write the ability. The skill was developed to accelerate this process.

4. **Coverage Measurements Are Critical**: After a new parser-improvement batch lands, coverage goes from e.g. 44% to 45.8%. But in a 99-card deck, global coverage doesn't matter — it matters if *your* deck is playable. Hence now also Commander-specific measurements.

5. **Concurrent Sessions**: The developer often runs multiple Claude instances on the same working directory. This means: every edit on shared docs (BACKLOG.md, Done_Backend.md) needed isolation. With `GIT_INDEX_FILE` temp indices, only the current changes are committed.

6. **Half-Implementations Are Expensive**: If a batch starts and needs a new mechanic but then doesn't finish it, it becomes a "deferred" ticket. Next time, the same mechanic is built by a *different* batch—but the original ticket never gets solved. That's wasted time. The discipline now: Either finish it, or implement it by hand (via `hand-author-card`), or move it to DEFERRED. No pretty halves.

## Phase 8: Current Status (September 2026)

### Coverage Status

- **Global Parser Coverage**: 45.86% (15,963 / 34,811 cards)
- **Commander-Legal Coverage**: 48.2% (15,332 / 31,830 cards) — this is what matters
- **Active Tickets**: PAR-117 (trigger-condition group subjects), the indefinite long tail (PAR-12)

### Architecture Highlights

1. **Separation of Concerns**:
   - Frontend (JS, no build, no state management)
   - Backend (Python, FastAPI, all game logic)
   - Card Parser (isolated from game engine, fail-closed)
   - Ability Catalogue (fallback for one-offs)

2. **The Layer System**: The RULE 613 layer engine is the backbone. Everything that permanently or ephemerally changes a permanent's characteristics goes through 7 layers.

3. **Priority Architecture**: Interactive Priority (RULE 117) is opt-in per session. Solo = automatic. Multiplayer = player-controlled. Bots = deterministic.

4. **Offline-Safe Startup**: The project starts without internet. No network calls except to cache new card data.

5. **Test/Production Isolation**: Previously, tests wiped the real card cache. Now separate `backend/cache/test/` with automatic reseed.

### Documentation as Code

- `CLAUDE.md`: Technical orientation document. Kept in sync.
- `Done_Backend.md` / `Done_Frontend.md`: Worklog (what was built, why), not chronological but per-feature organized.
- `BACKLOG.md`: Only open tickets. No history, no "closed" items. Curatorially read.
- `PARSER_LONG_TAIL.md`: Strategy for the indefinite tail (small card clusters, singletons, heuristics).

## Critical Lessons

### 1. Metrics Lie

A new parser rule looks like "+20 cards." But what really matters: do *your* decks work? And do they really work or only in parse tests? The solution: `parser_probe.py` (parse verdict) AND `engine_bench.py` (execute test with real GameEngine).

### 2. Half-Implementations Are Expensive

A primitive marked "deferred" doesn't mean "we'll do that later." It means "we're deferring the debt." That debt gets rediscovered 4 months later by another batch and deferred again. The discipline: If you start it, finish it—or do it by hand, or move it to DEFERRED. No pretty halves.

### 3. Fail-Closed Is Better Than Half-Working

A card that is `UNMODELED` doesn't work. A card that is `MODELED` is guaranteed to work correctly. That's the opposite of many other projects where "mostly working" is the norm.

### 4. Decompose, Don't Fuse

ENG-37 taught: Instead of hundreds of specialized `XYZ_Effect` classes, prefer 5 composition primitives and combinatorics. The code gets longer (more nesting), but more readable and maintainable.

### 5. Isolation Is Critical

Multiple sessions on the same working directory = everyone needs their own test cache, own config state. The solution wasn't elegant, but it works: `MTG_CACHE_DIR` env var + temporary `GIT_INDEX_FILE`.

### 6. The Parser Is Unfinished and Always Will Be

With 30,000 cards, there's always a card with its own syntax. Accepting that and having an escape valve (hand-author-card) is cheaper than trying to parse every variation.

## Where DeckLab Stands Today

DeckLab is not a commercial service like HearthStone Online or Magic Arena. It's a **rules-accurate game engine for yourself**, built on the conviction that true rules accuracy is more important than 99% coverage.

The project has:

- ✅ A fully implemented RULE 613 layer engine
- ✅ Four major features (Goldfish solo, Replay/Puzzle, Multiplayer with bots, Dynamic Deck Analysis)
- ✅ Interactive Priority (RULE 117) for multiplayer
- ✅ Board construction & editing (Replay mode with JSON save/load)
- ✅ Statistical deck analysis (simulated games, opening hand quality, mana curve validation)
- ✅ 45%+ oracle-text parser coverage (zero regressions)
- ✅ German interface
- ✅ Offline-safe startup
- ✅ Concurrent-session discipline & process parallelization

What's not implemented:
- ❌ User accounts (authentication)
- ❌ Elo / matchmaking
- ❌ Streaming / spectate
- ❌ Visual 3D cards
- ❌ Stickers (intentional non-goal)
- ❌ About 50 card clusters needing their own parser grammar

The project is not "done." It never will be — Magic is a living game, and every new set brings new mechanics. But it's **stable**. The engine works. Real decks play to completion. New batches always bring +N more cards and 0 regressions.

## For the Future

The next major focus: **the long tail**. 15,000 unmodeled cards are many. But if only 100 of them are in your decks, the number is irrelevant. The emphasis should be on deck coverage, not cache coverage.

Tools for that already exist: `scripts/commander_tail_report.py`, `scripts/deck_coverage.py`. The idea is to sort the Commander-legal cards by "which are in real decks" and start there.

---

**TL;DR**: DeckLab was a journey from "I want to test a deck" to "I built a full MTG rules engine"—in 2.5 months. Along the way: detours (ENG-37), setbacks (parser coverage is hard), and surprising insights (fail-closed is gold, half-implementations are expensive). Today it works. Not perfect, but right.
