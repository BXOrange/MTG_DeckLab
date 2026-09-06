# MTG Analyzer: Claude Code Implementation Guide

---

# PART 1: SETUP & WORKFLOW

## Step 1: Initialize Your Project

```bash
# Create project directory
mkdir mtg-analyzer
cd mtg-analyzer

# Initialize git (for version control)
git init

# Create Python project structure
mkdir -p backend frontend docs

# Backend structure
mkdir -p backend/mtg_analyzer/{models,services,rules,effects,engine}
touch backend/requirements.txt
touch backend/setup.py

# Frontend structure
mkdir -p frontend/src/{components,pages,services,styles}
touch frontend/package.json

# Create README to track progress
touch README.md
touch IMPLEMENTATION_STATUS.md
```

## Step 2: Version Control & Claude Code Integration

```bash
# Create .gitignore
cat > .gitignore << 'EOF'
__pycache__/
*.py[cod]
*.egg-info/
node_modules/
.env
.DS_Store
*.db
venv/
dist/
build/
EOF

git add .
git commit -m "Initial project setup"
```

## Step 3: Use Claude Code to Start

```bash
# Install Claude Code CLI (if not already installed)
npm install -g @anthropic-ai/claude-code

# Start Claude Code session with project context
claude-code --project mtg-analyzer --spec ./docs/ARCHITECTURE.md
```

**What this does:**
- Loads your project into Claude's context
- Claude has access to all files
- You can ask Claude to create/modify files
- Full IDE-like experience from CLI

---

# PART 2: STRUCTURED PROMPT TEMPLATE FOR CLAUDE CODE

When working with Claude Code, use this template for maximum effectiveness:

## Template 1: Create a New Module

```
I'm implementing an MTG game engine in Python. 

CONTEXT:
- Architecture: Phases as sequences, Effects as classes, Service Registry pattern
- I'm on Phase 1: Data Layer
- Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2: Effect Type Hierarchy)

TASK:
Create backend/mtg_analyzer/effects.py with:

1. GameEffect (abstract base class)
   - Abstract methods: apply(), can_apply()
   - Properties: source_card

2. StaticEffect (subclass)
   - Properties: duration, target
   - Implements: apply()

3. TriggeredAbility (subclass)
   - Properties: trigger_event, trigger_condition, effect
   - Methods: check_trigger(), on_trigger()

4. ReplacementEffect (subclass)
   - Properties: event_type, replacement_fn
   - Methods: apply_replacement()

5. ActivatedAbility (subclass)
   - Properties: cost, can_activate, effect
   - Methods: can_activate()

REQUIREMENTS:
- Type hints on all methods
- Docstrings referencing RULE numbers where applicable
- No implementation yet (just interfaces/structure)
- Follow Python best practices (PEP 8)

OUTPUT:
- Code with proper structure
- Brief docstring for each class
```

## Template 2: Implement Logic

```
CONTEXT:
- Phase: 2 (Rules Engine)
- Current task: Implement Replacement Effect Stacking (RULE 616)
- Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 3)

IMPLEMENTATION TASK:
In backend/mtg_analyzer/effects.py, implement ReplacementEffectStack:

```python
class ReplacementEffectStack:
    def apply_replacement_effects(self, event, context):
        # RULE 616: Find applicable replacements
        # RULE 616.1: Active player orders if multiple
        # Apply each replacement to current event
        # Return final event
        
    def find_applicable_replacements(self, event, context):
        # Iterate through all permanents
        # Check each effect's event_type
        # Filter by can_apply()
        # Return list
```

ALGORITHM:
[Reference the exact algorithm from the docs]

TESTS:
After implementation, create test_replacement_effects.py with:
- Test single replacement
- Test multiple replacements (ordering)
- Test replacement chain (replacement replaces replacement)
- Test event becomes None (event prevented)

OUTPUT:
- Full implementation
- Unit tests that pass
```

## Template 3: Integrate Components

```
CONTEXT:
- Phase: 3 (Game Loop)
- Current task: Connect GameState with Effects
- Previous: Created effects.py, game_state.py

INTEGRATION TASK:
In backend/mtg_analyzer/engine/game_engine.py:

1. Import: GameState, GameEffect, ReplacementEffectStack
2. Create GameEngine class with:
   - __init__(game_state: GameState)
   - apply_effect(effect: GameEffect)
   - register_effect(effect: GameEffect)
   - emit_event(event_type: str, context: dict)
   - find_applicable_effects(event: Event)

3. Implement event flow:
   - Event triggered
   - Find applicable effects
   - Check RULE 616 ordering
   - Apply each effect
   - Update game_state
   - Fire event callbacks

TEST:
Create test_game_engine.py with integration tests

OUTPUT:
- GameEngine class fully implemented
- All tests passing
- Integration between GameState and Effects working
```

---

# PART 3: PHASE-BY-PHASE IMPLEMENTATION WITH CLAUDE CODE

## Phase 1: Data Layer (Weeks 1-2)

### Week 1, Day 1-3: Card Model

```bash
# Prompt 1: Create Card model
claude-code --task "
PHASE: 1 (Data Layer)
TASK: Create backend/mtg_analyzer/models/card.py

Implement Card class with ALL attributes from spec:
- Identity: id, name, set_code
- Casting: mana_cost (dict), converted_mana_cost, color_identity
- Type: type_line, is_creature, is_instant, is_land, etc.
- Creature stats: power, toughness (optional)
- Text: oracle_text
- Images: image_uri_small, image_uri_normal, image_uri_large
- Legality: is_banned_in_commander, legality_commander
- Metadata: loaded_at, last_updated

REQUIREMENTS:
- Type hints
- Validation in __init__ (e.g., power/toughness only for creatures)
- to_dict() method (for JSON serialization)
- from_dict() class method (for loading)
- __repr__ for debugging

CREATE ALSO:
- test_card.py with comprehensive tests
"
```

### Week 1, Day 3-5: Deckliste Parser

```bash
claude-code --task "
PHASE: 1 (Data Layer)
TASK: Create backend/mtg_analyzer/parser/deckliste_parser.py

Implement DecklisteParser class:

1. parse(input_string) -> list[dict]
   - Input: '4x Lightning Bolt\n2x Counterspell\n...'
   - Output: [{'name': 'Lightning Bolt', 'qty': 4}, ...]
   - Support formats: '4x Card', 'Card x4', 'Archidekt', 'MTGArena'

2. Validator class:
   - validate_commander(card) -> bool
   - validate_singleton(cards) -> (bool, errors)
   - validate_color_identity(cards, commander) -> (bool, errors)
   - validate_ban_list(cards) -> (bool, errors)
   - validate_deck(cards, commander) -> DeckValidationResult

REQUIREMENTS:
- Clean error messages with suggestions
- Flexible format detection
- Case-insensitive name matching
- Return validation results with detailed errors

CREATE ALSO:
- test_parser.py with various deck formats
- test_validator.py with legal/illegal decks
"
```

### Week 2, Day 1-3: Game State Model

```bash
claude-code --task "
PHASE: 1 (Data Layer)
TASK: Create backend/mtg_analyzer/models/game_state.py

Implement:

1. Player class:
   - id, name, life_total
   - Zones: hand, library, graveyard, battlefield, exile, command_zone
   - mana_pool (ManaPool instance)
   - is_active_player, has_priority

2. ManaPool class:
   - white, blue, black, red, green, colorless (int each)
   - can_pay(cost: dict) -> bool
   - pay(cost: dict) -> bool
   - add_mana(color: str, amount: int)
   - empty() -> clear pool

3. GameState class:
   - players: list[Player]
   - active_player_index: int
   - stack: list[StackItem]
   - internal_turn (number, turn_nr, player_id), current_phase, current_step
   - priority_player_index
   - is_game_over, winner
   - game_log: list[str]

4. Methods:
   - move_card(card, from_zone, to_zone)
   - shuffle_zone(zone)
   - player_has_priority(player_id) -> bool
   - is_active_player(player_id) -> bool
   - get_phase_index() -> int

REQUIREMENTS:
- Immutable zones (can't directly modify, use move_card)
- Proper zone tracking
- Turn number always increments
- Priority management
- Detailed game_log for debugging

CREATE ALSO:
- test_game_state.py
"
```

### Week 2, Day 4-5: Database Schema & Scryfall Integration

```bash
claude-code --task "
PHASE: 1 (Data Layer)
TASK: Create backend/mtg_analyzer/data/database.py

Implement:

1. CardDatabase class:
   - load_from_sqlite(path)
   - load_from_scryfall_cache(json_file)
   - get_card(name) -> Card
   - search_cards(query) -> list[Card]
   - save_to_db(card)

2. ScryfallIntegration class:
   - fetch_card(name) -> dict
   - fetch_multiple(names: list) -> list[dict]
   - handle errors and retries
   - cache responses locally

3. LazyCardLoader class:
   - load_deck_cards(card_names) -> list[Card]
   - Check DB first
   - Fetch from Scryfall if missing
   - Store in DB
   - Return Card objects

SCHEMA (SQLite):
CREATE TABLE cards (
    id UUID PRIMARY KEY,
    name VARCHAR(255) UNIQUE,
    loaded_at TIMESTAMP,
    mana_cost, type_line, oracle_text, ...,
    image_uri_small, image_uri_normal, image_uri_large,
    ... (all Card attributes)
)

REQUIREMENTS:
- Async/await for Scryfall API calls
- Proper error handling
- Caching strategy
- Connection pooling
- Indexed lookups

CREATE ALSO:
- test_database.py
- test_scryfall_integration.py
- fixtures with sample cards
"
```

## Phase 2: Rules Engine (Weeks 3-4)

### Day 1-2: Effect System (Foundation)

```bash
claude-code --task "
PHASE: 2 (Rules Engine)
TASK: Create backend/mtg_analyzer/effects/effect_base.py

Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2)

Implement effect hierarchy:

1. GameEffect (abstract)
2. StaticEffect
3. TriggeredAbility
4. ReplacementEffect
5. ActivatedAbility

Then create:

backend/mtg_analyzer/effects/effect_registry.py:
- EffectRegistry class
- register(name, factory)
- create(name, params)
- List all registered effects

backend/mtg_analyzer/effects/core_effects.py:
- DealDamageEffect
- DrawCardEffect
- DiscardEffect
- DestroyEffect
- CounterSpellEffect
- SearchEffect (tutor)

Each effect:
- Proper __init__ with validation
- apply(context) implementation
- can_apply(context) check
- to_dict() for serialization

CREATE ALSO:
- test_effects.py
- test_effect_registry.py
"
```

### Day 3-4: Replacement Effect Stacking (RULE 616)

```bash
claude-code --task "
PHASE: 2 (Rules Engine)
TASK: Implement ReplacementEffectStack

Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 3 & 7)

Create backend/mtg_analyzer/effects/replacement_stack.py:

ReplacementEffectStack class:
- apply_replacement_effects(event, context) -> Event
  - Find applicable replacements
  - Order them (RULE 616.1)
  - Apply each in order
  - Handle event becoming None
  - Return final event

- find_applicable_replacements(event, context) -> list
- order_replacements(effects, context, active_player)

ALGORITHM (from docs):
[Copy exact algorithm from Part 3]

EDGE CASES to handle:
- Multiple replacements for same event
- Replacements replacing replacements
- Event becoming None (prevented)
- Win/loss condition replacements

TESTS to write:
- Single replacement
- Multiple replacements (order matters)
- Replacement chain (3+ deep)
- Event prevention
- Actual MTG scenarios (examples from Part 7)

CREATE ALSO:
- test_replacement_effects.py with real scenarios
"
```

### Day 5: Phases & Steps as Sequences

```bash
claude-code --task "
PHASE: 2 (Rules Engine)
TASK: Create sequence-based phase engine

Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 1)

Create backend/mtg_analyzer/engine/phases.py:

1. GamePhase class:
   - name, order, effect_points
   - hooks: before_phase, body, after_phase

2. TurnSequence class:
   - phases: list[GamePhase]
   - Can be modified at runtime (card effects)
   - execute_turn(player, game_state)
   - skip_phase(phase_name)
   - reorder_phases(new_order)

3. TURN_STRUCTURE constant:
   - Define correct phase order (from RULE 500)
   - Each step with RULE reference

REQUIREMENTS:
- Phases/steps not hardcoded
- Can be skipped/reordered
- Fire events at right times
- Check should_skip_phase() for effects

TESTS:
- Normal turn execution
- Skip phase (test card effect)
- Reorder phases
- Events fire in correct order
"
```

---

# PART 4: CLAUDE CODE BEST PRACTICES

## 1. Keep Context Window Clear

```bash
# Use focused prompts, not massive ones
# Break into smaller tasks

GOOD:
  "Implement Card class with these 5 attributes..."
  
BAD:
  "Implement entire Phase 1 Data Layer in one prompt"
```

## 2. Build Incrementally

```bash
# Structure:
Phase 1:
  Week 1: Models (Card, Player, GameState)
  Week 2: Parser, Database, Scryfall Integration
  
Phase 2:
  Week 3: Effects (base classes + registry)
  Week 4: Replacement stacking, Phases
  
Do NOT try to build everything at once.
```

## 3. Always Request Tests

```bash
# Every prompt should include:
"CREATE ALSO:
- test_XXX.py with comprehensive tests
- Test these scenarios: [list]"

This ensures code is testable from the start.
```

## 4. Reference Documentation

```bash
# In every prompt:
"Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART X)"

This keeps Claude aligned with your spec.
```

## 5. Commit After Each Task

```bash
# After Claude finishes a module:
git add .
git commit -m "Phase 1 (Data Layer): Implement Card model"
git commit -m "Phase 1 (Data Layer): Implement DecklisteParser"

Atomic commits = easy rollback if needed
```

---

# PART 5: EXAMPLE SESSION: Implement Card Model

Here's how an actual Claude Code session would go:

## Session Start

```bash
cd mtg-analyzer
claude-code --project . --spec docs/ARCHITECTURE.md
```

## Prompt 1: Create Card Model

```
PHASE: 1 (Data Layer)
TASK: Create Card model

Reference: /docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 1: Card Data Model)

Create backend/mtg_analyzer/models/card.py with Card class:

ATTRIBUTES (exactly as specified):
- id: str (UUID)
- name: str
- mana_cost: dict[str, int] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
- converted_mana_cost: int
- color_identity: set[str]
- type_line: str
- is_creature: bool
- is_instant: bool
- is_sorcery: bool
- is_land: bool
- power: int | None (only for creatures)
- toughness: int | None (only for creatures)
- oracle_text: str
- image_uri_small: str
- image_uri_normal: str
- image_uri_large: str
- is_legendary: bool
- has_partner: bool
- partner_with: str | None

VALIDATION in __init__:
- power/toughness only if is_creature
- color_identity must be valid colors
- type_line non-empty
- name non-empty

METHODS:
- to_dict() -> dict (for JSON)
- from_dict(data: dict) -> Card (class method)
- __repr__ for debugging
- __eq__ for comparison

REQUIREMENTS:
- Full type hints
- Docstrings
- No external dependencies yet

TESTS (create test_card.py):
- Create creature with stats
- Create land without stats
- Validation errors (invalid color, etc.)
- Serialization round-trip (to_dict → from_dict)
```

## Claude's Response: Full Implementation

Claude would create:
- backend/mtg_analyzer/models/card.py (complete)
- backend/mtg_analyzer/models/__init__.py
- backend/tests/test_card.py (complete with tests)

## Prompt 2: Integrate Card into Models

```
Great! Now integrate Card into the data layer.

TASK: Create Player model that uses Card

Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2: GameState Model)

Create backend/mtg_analyzer/models/player.py:

Player class needs:
- id: str
- name: str
- life_total: int = 20
- hand: list[Card] = []
- library: list[Card] = []
- graveyard: list[Card] = []
- ... (all zones from spec)
- mana_pool: ManaPool (create this too)

ManaPool class:
- white, blue, black, red, green, colorless: int
- can_pay(cost: dict) -> bool (validate colors)
- pay(cost: dict) -> bool (deduct from pool)
- add_mana(color: str, amount: int)

TESTS:
- Add card to hand
- Move card between zones
- Mana pool: pay valid cost
- Mana pool: fail with insufficient mana
- Mana pool: color requirements
```

## And so on...

Each prompt builds on previous ones, growing the codebase incrementally.

---

# PART 6: CONTINUOUS INTEGRATION

As you build, set up testing:

```bash
# After Phase 1 is complete:
pytest backend/tests/test_*.py -v

# Coverage report:
pytest --cov=backend/mtg_analyzer

# Watch mode (auto-run tests):
pytest-watch backend/tests/
```

This ensures code quality from day 1.

---

# PART 7: THE WORKFLOW LOOP

For each Phase:

```
1. READ SPEC (reference the docs)
   └─ "Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md"

2. WRITE PROMPT (with exact requirements)
   └─ "Implement X with properties A, B, C..."

3. REVIEW CODE (Claude delivers, you check)
   └─ "Does this match the spec?"

4. RUN TESTS (make sure it works)
   └─ pytest should pass

5. COMMIT (save progress)
   └─ git commit -m "Phase X: Feature done"

6. NEXT PROMPT (build on previous)
   └─ "Now implement Y which uses X..."
```

---

# PART 8: HANDLING CLAUDE CODE LIMITATIONS

## If Claude Misunderstands Requirements

```
CLARIFY in the prompt:

"This is RULE 616 from MTG specification (see attached doc).
It means:

1. When multiple effects modify same event
2. Player chooses order of application
3. Each modifies the event for the next

Example:
- Effect A: 'draw 2 instead of 1'
- Effect B: 'mill instead of draw'
- Result: Mill 2 (B applied after A)

Implement exactly this logic, not simplified version."
```

## If Tests Don't Pass

```
REQUEST: "Debug these failing tests:
- test_replacement_effects.py::test_multiple_replacements

Expected: Mill 2 cards
Actual: Mill 1 card

The issue is likely in how replacements are ordered.
Reference: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md PART 3"
```

## If Code Doesn't Match Spec

```
"I notice the implementation doesn't handle [specific case].
Reference in spec: /docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md PART X says:
'[exact quote from spec]'

Please update implementation to handle this case."
```

---

# SUMMARY: Quick Start Checklist

```bash
□ Initialize project (git, directory structure)
□ Read Phase 1 spec (/docs/01-06_*.md)
□ Prompt 1: Create Card model
□ Run: pytest backend/tests/test_card.py
□ Commit: "Phase 1: Card model"
□ Prompt 2: Create Parser
□ Commit: "Phase 1: DecklisteParser"
□ Prompt 3: Create GameState
□ Commit: "Phase 1: GameState & Player"
□ Prompt 4: Database & Scryfall
□ Commit: "Phase 1: Database complete"
□ Read Phase 2 spec (/docs/07_*.md)
□ Prompt 5: Create Effects
□ Commit: "Phase 2: Effect system"
□ Prompt 6: Replacement stacking
□ Commit: "Phase 2: Replacement effects"
□ Prompt 7: Phases as sequences
□ Commit: "Phase 2: Phase engine"

→ Phase 1 & 2 DONE (4 weeks)
```

Start with Phase 1 Day 1, follow the prompts, commit after each task.

You've got the complete spec. Now execute it. 🎯
