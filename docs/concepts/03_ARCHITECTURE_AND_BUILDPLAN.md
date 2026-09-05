# MTG Deck Analyzer: Architecture & Build Plan

---

# PART 1: ARCHITECTURE OVERVIEW

## System Layers (Top-Down)

```
┌─────────────────────────────────────────────────────────┐
│ UI LAYER (Phase 4-5)                                    │
│ ├─ CLI Interface                                        │
│ ├─ Game State Display                                   │
│ ├─ Player Input Handler                                 │
│ └─ Error Message Formatter                              │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ GAME ENGINE LAYER (Phase 3-5)                           │
│ ├─ Turn Manager (Phase progression)                     │
│ ├─ Phase Manager (Step progression)                     │
│ ├─ Priority Manager (Who can act?)                      │
│ ├─ Action Validator (Is this legal?)                    │
│ ├─ Event Bus (Coordinate rule events)                   │
│ └─ Game State Manager (Track current state)             │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ RULES ENGINE LAYER (Phase 2-3)                          │
│ ├─ Casting Validator (RULE 601)                         │
│ ├─ Stack Manager (RULE 608)                             │
│ ├─ Priority System (RULE 117)                           │
│ ├─ Triggered Ability Resolver (RULE 603/607)            │
│ ├─ Mana System (RULE 504)                               │
│ ├─ Combat Resolver (RULE 500.2)                         │
│ ├─ State-Based Actions (RULE 704)                       │
│ └─ Commander Rules (Singleton, Color Identity)          │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ CARD SERVICES LAYER (Phase 2-3)                         │
│ ├─ Card Service Registry                                │
│ ├─ Generic Card Effects (Damage, Draw, Discard, etc.)   │
│ ├─ Specific Card Services (as needed)                   │
│ └─ Effect Resolution                                    │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ DATA LAYER (Phase 1)                                    │
│ ├─ Card Database (Scryfall Cache + Local)               │
│ ├─ Deck Parser & Storage                                │
│ ├─ Deck Validator (Commander Rules)                     │
│ ├─ Game State Model                                     │
│ └─ Player Model                                         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ LLM INTEGRATION (Phase 6) [Parallel to above]           │
│ ├─ LLM API Client                                       │
│ ├─ Prompt Engineering                                   │
│ └─ Output Parser                                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ BOT AI (Phase 7) [Depends on Game Engine]               │
│ ├─ Action Evaluator                                     │
│ ├─ Strategy Engine                                      │
│ └─ Decision Maker                                       │
└─────────────────────────────────────────────────────────┘
```

---

# PART 2: COMPONENT DETAILS

## Data Layer Components

### D1: Card Database
**Responsibility**: Store and retrieve MTG card information

**Inputs**:
- Scryfall API (initial load)
- Local cache (JSON/SQLite)

**Outputs**:
- Card object with full attributes

**Attributes per Card**:
```python
class Card:
    # Identity
    id: str                              # Scryfall UUID
    name: str
    set_code: str
    
    # Casting
    mana_cost: dict[str, int]           # {W: 1, U: 2, B: 0, R: 1, G: 0, C: 0}
    converted_mana_cost: int
    color_identity: set[str]            # {"W", "R"} for Izzet
    
    # Type
    type_line: str                      # "Creature — Goblin Wizard"
    is_creature: bool
    is_instant: bool
    is_sorcery: bool
    is_land: bool
    is_enchantment: bool
    is_legendary: bool
    has_partner: bool                   # "Partner" or "Partner with X"
    partner_with: Optional[str]         # If "Partner with X"
    
    # Creature Stats
    power: Optional[int]                # If creature
    toughness: Optional[int]
    
    # Text
    oracle_text: str                    # Full rules text
    
    # Legality
    is_banned_in_commander: bool
    legality_commander: str             # "legal", "banned", "restricted"
```

### D2: Deck Parser & Validator
**Responsibility**: Parse decklists, validate against Commander rules

**Input Formats**:
- "4x Card Name"
- "Card Name x4"
- Archidekt format
- MTGArena format

**Validation Steps**:
1. Parse format (extract Card Name + Quantity)
2. Resolve names against Card DB
3. Extract Commander (first line, or "Commander: X")
4. Validate Singleton (exactly 1 copy each, except Basics/Commander)
5. Validate Legendary (Commander must be legendary)
6. Validate Partner (if applicable)
7. Validate Total Count (100 cards)
8. Validate Color Identity (all cards within Commander's color identity)
9. Validate Ban List (no banned cards)
10. Return: Legal (true/false) + Error List

### D3: Game State Model
**Responsibility**: Represent current game state

```python
class Player:
    id: str
    name: str
    life_total: int = 20
    hand: list[Card] = []
    library: list[Card] = []
    graveyard: list[Card] = []
    battlefield: list[Card] = []
    exile: list[Card] = []
    command_zone: list[Card] = []      # Commander(s)
    
    mana_pool: ManaPool                # Current mana available
    
    # Turn State
    is_active_player: bool
    has_priority: bool
    
    # Deck Info
    deck: Deck
    
class ManaPool:
    white: int = 0
    blue: int = 0
    black: int = 0
    red: int = 0
    green: int = 0
    colorless: int = 0
    
    def can_pay(self, mana_cost: dict[str, int]) -> bool:
        """Check if this pool can pay the cost"""
        # Implementation: Color requirements matter
        pass
    
    def pay(self, mana_cost: dict[str, int]) -> bool:
        """Subtract from pool, return success"""
        pass

class GameState:
    players: list[Player]               # Usually 2 (for MVP)
    active_player_index: int            # Who's turn is it?
    
    # Stack
    stack: list[StackItem]              # Spells/abilities awaiting resolution
    
    # Turn Info
    internal_turn: dict                 # number, turn_nr, player_id
    turn_nr: int                        # Complete circuit around the table
    current_phase: str                  # "beginning", "main1", "combat", "main2", "ending"
    current_step: str                   # "untap", "upkeep", "draw", etc.
    
    # Priority
    priority_player_index: int          # Who has priority?
    
    # Game Status
    is_game_over: bool
    winner: Optional[Player]
    game_log: list[str]                 # All actions
```

---

## Rules Engine Components

### R1: Casting Validator
**Responsibility**: Determine if a spell can be cast right now

**Logic**:
```
Can Cast(spell, current_state) if:
  1. Spell is in hand (or command_zone for Commander)
  2. Player has priority
  3. Spell type timing is legal:
     - Instant: Always (if has priority)
     - Sorcery: Main phase + active player + no spells on stack
     - Creature/Permanent: Like sorcery
  4. Player can pay mana cost
  5. All targets (if required) are valid
```

### R2: Stack Manager
**Responsibility**: Implement RULE 608 (Stack Resolution)

**LIFO Order**:
```python
class Stack:
    items: list[StackItem] = []         # LIFO: last item is top
    
    def push(self, item):
        """Add to top of stack"""
        self.items.append(item)
    
    def pop_top(self) -> StackItem:
        """Remove from top (last added)"""
        return self.items.pop()
    
    def resolve_next(self):
        """Resolve top spell/ability"""
        item = self.pop_top()
        item.resolve()
```

### R3: Priority Manager
**Responsibility**: Track priority, manage passes, handle responses

**Logic**:
```
Priority Flow:
1. Active player gets priority
2. Active player can:
   - Cast spell (spell goes on stack, priority passes)
   - Activate ability
   - Pass priority
3. If player passes:
   - Priority goes to opponent (if multiple players)
   - Opponent can respond
4. If both players pass with empty stack:
   - Current step/phase ends
5. If spell on stack and priority player passes:
   - Spell starts resolving
   - Other player can still respond with Instant
```

### R4: Triggered Ability Resolver
**Responsibility**: RULE 603 (Triggered Abilities) + RULE 607 (Ordering)

**Trigger Check**:
```
When event E occurs:
  For each permanent on battlefield:
    If permanent has triggered ability that triggers on E:
      If trigger condition is met:
        Add ability to stack (after state-based actions)
```

**Ordering (RULE 607.1)**:
```
If multiple triggered abilities trigger at same time:
  Active player chooses order
  Push to stack in that order (LIFO)
```

### R5: Mana System
**Responsibility**: RULE 504 (Mana Payment)

**Mana Production**:
```
When land is tapped:
  Add mana to player's mana pool
  Color depends on land type
```

**Mana Payment**:
```
When spell is cast:
  Check: Can player pay mana cost?
  Deduct from mana pool
  If insufficient: Cannot cast
```

**Color Identity Constraint** (Commander):
```
Can only use mana from colors in deck's color identity
Example: Izzet deck (U/R) cannot use Black mana
```

### R6: Combat Resolver
**Responsibility**: RULE 500.2 (Combat Phase)

**For MVP: Simplified Combat**
```
1. Active player declares attackers
   - Which creatures attack?
   - Must be untapped
   - Most creatures can attack (some have restrictions)
2. Defending player declares blockers
   - Which creatures block?
   - Can block attacking creature?
3. Resolve damage
   - Each creature deals damage to what it's attacking
   - Blocked creatures: deal damage to blockers
   - Unblocked: deal damage to player
4. Trigger combat abilities
   - Creatures that deal combat damage may trigger
```

### R7: State-Based Actions
**Responsibility**: RULE 704 (Automatic state checks)

**For MVP**: Simplified
```
After each action, check:
1. Is any player at 0 or negative life? → They lose
2. Did any creature reach 0 toughness? → Move to graveyard
3. Are there duplicate legendary permanents? → Keep one, others to graveyard
4. Did an Aura creature it enchants leave? → Aura to graveyard
```

---

## Game Engine Components

### G1: Turn Manager
**Responsibility**: Progress through turns

```
Turn Loop:
  while not game_over:
    for player in players:
      active_player = player
      player.untap_all_permanents()
      player.upkeep_trigger()
      player.draw_card()
      
      # Main phase
      player.main_phase_1()
      
      # Combat
      player.combat_phase()
      
      # Main phase 2
      player.main_phase_2()
      
      # Ending
      player.ending_phase()
      
      # Check game end
      if is_game_over():
        return winner
```

### G2: Phase Manager
**Responsibility**: Track current phase and enforce timing

```python
PHASES = [
    "beginning",      # (Untap → Upkeep → Draw)
    "main1",          # (Play land + spells)
    "combat",         # (Declare attackers/blockers)
    "main2",          # (Play land + spells)
    "ending"          # (Cleanup)
]

class PhaseManager:
    current_phase_idx: int = 0
    
    def advance_phase(self):
        self.current_phase_idx = (self.current_phase_idx + 1) % len(PHASES)
    
    def is_main_phase(self) -> bool:
        return self.current_phase in ["main1", "main2"]
    
    def is_active_player(self) -> bool:
        return player == active_player
```

### G3: Action Validator
**Responsibility**: Before executing any action, validate legality

```python
def validate_action(action, game_state) -> (bool, str):
    """
    Returns: (is_legal, error_message)
    """
    if action.type == "CAST_SPELL":
        # Check: Is spell castable right now?
        # Check: Can player pay mana?
        # Check: Are targets legal?
        pass
    elif action.type == "ATTACK":
        # Check: Is it combat phase?
        # Check: Are creatures untapped?
        # Check: Can they attack?
        pass
    elif action.type == "ACTIVATE_ABILITY":
        # Check: Does player have priority?
        # Check: Can player pay ability cost?
        pass
    elif action.type == "PASS":
        # Always legal (pass priority)
        return True, ""
```

### G4: Event Bus
**Responsibility**: Coordinate rule events

```python
class EventBus:
    listeners: dict[str, list[Callable]] = {}
    
    def on(self, event_type: str, callback: Callable):
        """Register listener for event"""
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)
    
    def emit(self, event_type: str, context: GameContext):
        """Fire event, call all listeners"""
        if event_type in self.listeners:
            for callback in self.listeners[event_type]:
                callback(context)

# Events
EVENTS = [
    "SPELL_CAST",
    "SPELL_RESOLVES",
    "SPELL_COUNTERED",
    "CREATURE_ENTERS",
    "CREATURE_DIES",
    "DAMAGE_DEALT",
    "CARD_DRAWN",
    "CARD_DISCARDED",
    "MANA_PRODUCED",
    "LAND_PLAYED",
    # ... more
]
```

---

## UI Layer Components

### U1: Game State Display
**Responsibility**: Show current game state in readable format

**Display**:
```
=== TURN 1 ===
Active Player: Player 1 (Main Phase 1)

PLAYER 1:
  Life: 20
  Hand: 7 cards [Lands: 2, Spells: 5]
  Library: 93 cards
  Graveyard: 0 cards
  Battlefield:
    - Island (untapped)
    - Mountain (untapped)
  Mana Pool: U R (2 mana available)

PLAYER 2:
  Life: 20
  Hand: 7 cards [Hidden]
  Library: 93 cards
  Graveyard: 0 cards
  Battlefield: Empty

STACK: Empty

---
[PLAYER 1's TURN]
What do you want to do?
1. Play land (if have unplayed land)
2. Cast spell (if can afford)
3. Activate ability
4. Pass priority
> 
```

### U2: Player Input Handler
**Responsibility**: Parse player commands, validate, execute

**Commands**:
- `cast <spell_name> [targeting info]` → Cast spell
- `attack [with creatures]` → Declare attackers
- `block [creature] with [blocker]` → Declare blockers
- `activate <ability>` → Activate ability
- `pass` → Pass priority
- `mulligan` / `keep` → Keep/mulligan decision

### U3: Error Message Formatter
**Responsibility**: User-friendly error messages

**Examples**:
```
"You can't cast Lightning Bolt: You need 1 Red mana, but only have 1 Blue"
"You can't attack with that creature: It has 'this creature can't attack'"
"Lightning Bolt is not a valid spell name. Did you mean 'Lightning Bolt'?"
```

---

## LLM Integration Components

### L1: LLM API Client
**Responsibility**: Call LLM API (Claude, etc.)

```python
class LLMClient:
    api_key: str
    model: str = "claude-3-sonnet"
    
    def analyze_deck(self, deck: Deck) -> DeckAnalysis:
        """Call LLM to analyze deck"""
        # Format deck for LLM
        deck_text = self.format_deck_for_llm(deck)
        
        # Create prompt
        prompt = self.create_analysis_prompt(deck_text)
        
        # Call API
        response = call_claude_api(prompt)
        
        # Parse response
        analysis = parse_llm_response(response)
        
        return analysis
```

### L2: Prompt Engineering
**Responsibility**: Create effective prompts for deck analysis

**Prompt Template**:
```
You are a Magic: The Gathering expert. Analyze this Commander deck:

[DECK LIST]

Provide analysis in JSON format with:
- primary_win_conditions: [list of main ways to win]
- win_condition_probability: {"early_game": %, "mid_game": %, "late_game": %}
- deck_archetype: "Aggro" | "Midrange" | "Control" | "Combo" | "Ramp" | "Other"
- archetype_purity_score: 0-10 (how pure is this archetype?)
- key_synergies: [list of card interactions]
- potential_issues: [weaknesses of the deck]
- deck_cohesion_score: 0-10 (how well do cards work together?)
```

### L3: Output Parser
**Responsibility**: Parse LLM response into structured data

```python
class LLMOutputParser:
    def parse_response(self, llm_text: str) -> DeckAnalysis:
        """Parse JSON/structured output from LLM"""
        # Extract JSON
        json_match = re.search(r'\{.*\}', llm_text, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON found in LLM response")
        
        data = json.loads(json_match.group())
        
        # Validate required fields
        analysis = DeckAnalysis(
            win_conditions=data['primary_win_conditions'],
            win_probability=data['win_condition_probability'],
            archetype=data['deck_archetype'],
            synergies=data['key_synergies'],
            issues=data['potential_issues'],
            cohesion_score=data['deck_cohesion_score']
        )
        
        return analysis
```

---

## Bot AI Components

### B1: Action Evaluator
**Responsibility**: Score each possible action

```python
class ActionEvaluator:
    def evaluate_action(self, action: Action, game_state: GameState) -> float:
        """Score from 0-100"""
        score = 0
        
        if action.type == "CAST_SPELL":
            spell = action.card
            
            # Priority 1: Win condition spells
            if spell.is_win_condition:
                score += 50
            
            # Priority 2: Removal (vs opponent threats)
            if spell.is_removal:
                opponent_threats = get_opponent_threats(game_state)
                if opponent_threats:
                    score += 40
            
            # Priority 3: Draw/Acceleration
            if spell.draws_cards:
                score += 30
            elif spell.produces_mana:
                score += 25
            
            # Priority 4: Generic spell
            else:
                score += 10
        
        elif action.type == "ATTACK":
            # Score attacking creatures
            # Based on power, abilities, etc.
            pass
        
        return score

class StrategyEngine:
    """Different strategies for different deck types"""
    
    def get_action_priority(self, deck_archetype: str) -> list[str]:
        """Return action priority based on deck type"""
        if deck_archetype == "Aggro":
            return ["ATTACK", "CAST_SPELL_AGGRESSIVE", "PASS"]
        elif deck_archetype == "Control":
            return ["CAST_REMOVAL", "DRAW", "CAST_THREAT", "PASS"]
        elif deck_archetype == "Combo":
            return ["CAST_COMBO_PIECE", "CAST_TUTOR", "PASS"]
        else:
            return ["CAST_THREAT", "CAST_REMOVAL", "PASS"]
```

### B2: Decision Maker
**Responsibility**: Choose best action from available options

```python
class BotDecisionMaker:
    evaluator: ActionEvaluator
    strategy: StrategyEngine
    
    def choose_action(self, game_state: GameState) -> Action:
        """Choose best action for this turn"""
        
        # Get possible actions
        possible_actions = get_legal_actions(game_state)
        
        # Score each
        scores = [(action, self.evaluator.evaluate_action(action, game_state)) 
                  for action in possible_actions]
        
        # Sort by score
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Return highest scoring
        best_action = scores[0][0]
        return best_action
```

---

# PART 3: DATA MODELS (Summary)

## Core Models

```python
# Card
class Card:
    id, name, mana_cost, type_line, power, toughness, oracle_text, color_identity, is_legendary, is_banned_in_commander

# Deck
class Deck:
    commander: Card
    cards: list[tuple[Card, int]]  # (card, quantity)
    
# Player
class Player:
    id, name, life_total, hand, library, graveyard, battlefield, exile, command_zone, mana_pool, is_active_player

# GameState
class GameState:
    players, stack, internal_turn, turn_nr, current_phase, priority_player_index, is_game_over, game_log

# Action
class Action:
    type: "CAST_SPELL" | "ATTACK" | "BLOCK" | "ACTIVATE_ABILITY" | "PASS"
    card: Optional[Card]
    targets: Optional[list]
    context: GameContext
```

---

# PART 4: SEVEN-PHASE BUILD PLAN

## PHASE 1: Rules Infrastructure (Weeks 1-2)

**Goal**: Foundation for everything else - data models and parsing

### Tasks:

**1.1 Card Database Setup**
- [ ] Create Card class with all attributes
- [ ] Set up Scryfall API integration
- [ ] Download 2000+ cards to local cache (JSON or SQLite)
- [ ] Create card lookup function (<100ms)
- [ ] Tests: Card lookup, color_identity calculation

**1.2 Deckliste Parser & Validator**
- [ ] Implement parser for multiple formats
  - [ ] "4x Card Name"
  - [ ] "Card Name x4"
  - [ ] Archidekt format
  - [ ] MTGArena format
- [ ] Implement Commander validator (legendary check, partner rules)
- [ ] Implement Singleton validator (max 1 copy except Basics)
- [ ] Implement Color Identity validator
- [ ] Implement Ban List validator
- [ ] Tests: All parser formats, validation rules

**1.3 Game State Models**
- [ ] Implement Player class
- [ ] Implement GameState class
- [ ] Implement Deck class
- [ ] Implement ManaPool class
- [ ] Implement Stack class (basic LIFO)
- [ ] Tests: Model correctness, state updates

**1.4 Rules Infrastructure**
- [ ] Create Rule constants (RULE 601, etc.)
- [ ] Create Event types (SPELL_CAST, etc.)
- [ ] Create Action types
- [ ] Tests: Constants are correct

### Deliverables:
- ✅ Card database with 2000+ cards
- ✅ Working deckliste parser (all formats)
- ✅ Deck validator against Commander rules
- ✅ Game state models
- ✅ Unit tests (>90% pass)

### Success Criteria:
- Can load any Commander deck
- Validation catches all illegal decks
- Models are clean and testable

---

## PHASE 2: Core Rules Engine (Weeks 3-4)

**Goal**: Implement MTG rules so game is playable

### Tasks:

**2.1 Casting Validator (RULE 601)**
- [ ] Implement RULE 601.2a (Sorcery - main phase only)
- [ ] Implement RULE 601.3a (Instant - any time)
- [ ] Implement Mana cost validation
- [ ] Implement Color requirements
- [ ] Implement Timing constraints
- [ ] Tests: Each rule subtype

**2.2 Stack Manager (RULE 608)**
- [ ] Implement LIFO stack
- [ ] Implement StackItem for spells/abilities
- [ ] Implement spell resolution flow
- [ ] Implement countering (RULE 116)
- [ ] Tests: LIFO ordering, resolution

**2.3 Mana System (RULE 504)**
- [ ] Implement mana pool (colors)
- [ ] Implement land tapping for mana
- [ ] Implement mana payment validation
- [ ] Implement mana color requirements
- [ ] Implement Commander color identity constraint
- [ ] Implement mana pool cleanup (end of phase)
- [ ] Tests: Mana payments, colors

**2.4 Priority System (RULE 117)**
- [ ] Implement priority tracking
- [ ] Implement priority passing rules
- [ ] Implement "both players pass" logic
- [ ] Implement response capability (Instants, etc.)
- [ ] Tests: Priority flow

**2.5 Triggered Ability Resolver (RULE 603/607)**
- [ ] Implement trigger detection
- [ ] Implement trigger checking
- [ ] Implement trigger ordering (RULE 607.1)
- [ ] Implement trigger stack resolution
- [ ] Tests: Multiple simultaneous triggers

**2.6 Card Effect Services**
- [ ] Generic damage service
- [ ] Generic draw service
- [ ] Generic discard service
- [ ] Generic destroy service
- [ ] Generic counter service
- [ ] Generic tutor/search service
- [ ] Tests: Each effect type

### Deliverables:
- ✅ Casting validator for all spell types
- ✅ Working LIFO stack
- ✅ Mana system with color identity
- ✅ Priority system
- ✅ Triggered ability resolver
- ✅ 6+ card effect services
- ✅ Unit tests (>90% pass)

### Success Criteria:
- All RULE 601/608/504/603/607 implemented
- Can play 10-turn game manually
- Rules are correct against actual MTG

---

## PHASE 3: Game Loop & State Management (Weeks 5-6)

**Goal**: Automate game flow so game plays itself (with player decisions)

### Tasks:

**3.1 Turn Manager**
- [ ] Implement turn progression (1,2,3,...)
- [ ] Implement phase progression (Beginning → Main I → Combat → Main II → Ending)
- [ ] Implement step progression (Untap → Upkeep → Draw, etc.)
- [ ] Implement automatic step execution
- [ ] Implement turn end cleanup
- [ ] Tests: Turn/phase/step correctness

**3.2 Phase Manager**
- [ ] Implement beginning phase (untap, upkeep, draw)
- [ ] Implement main phases
- [ ] Implement combat phase
- [ ] Implement ending phase
- [ ] Tests: Phase rules

**3.3 Combat Resolver (RULE 500.2)**
- [ ] Implement attacker declaration
- [ ] Implement blocker declaration
- [ ] Implement combat damage resolution
- [ ] Implement block/damage rules
- [ ] Tests: Combat scenarios

**3.4 State-Based Actions (RULE 704)**
- [ ] Implement zero toughness check
- [ ] Implement duplicate legendary check
- [ ] Implement aura enchantment check
- [ ] Implement zero/negative life check
- [ ] Tests: Each state-based action

**3.5 Action Validator**
- [ ] Implement comprehensive action validation
- [ ] Validate spell casting legality
- [ ] Validate targeting legality
- [ ] Validate ability activation legality
- [ ] Validate attack/block legality
- [ ] Tests: Illegal actions rejected, legal actions allowed

**3.6 Event Bus & Triggering**
- [ ] Implement event bus (publish/subscribe)
- [ ] Implement all major events (SPELL_CAST, CREATURE_ENTERS, etc.)
- [ ] Implement event triggering at correct times
- [ ] Tests: Events fire correctly

### Deliverables:
- ✅ Working turn/phase/step loop
- ✅ Combat resolution
- ✅ State-based actions
- ✅ Comprehensive action validation
- ✅ Event bus with major events
- ✅ Integration tests (full game scenarios)

### Success Criteria:
- Can play 10 full turns without errors
- All phases/steps execute correctly
- Combat works correctly
- Events trigger at correct times

---

## PHASE 4: UI & Player Interaction (Weeks 7-8)

**Goal**: Make game playable by humans (Goldfisch-Modus)

### Tasks:

**4.1 Game State Display**
- [ ] Implement CLI display of game state
- [ ] Show player info (life, hand size, library)
- [ ] Show battlefield (permanents)
- [ ] Show stack
- [ ] Show mana pool
- [ ] Show turn/phase info
- [ ] Show graveyard/exile
- [ ] Make it readable (formatting, colors if possible)
- [ ] Tests: Display correctness

**4.2 Player Input Handler**
- [ ] Implement command parsing (cast, attack, block, pass, etc.)
- [ ] Implement targeting system (select target from valid list)
- [ ] Implement spell casting input
- [ ] Implement attack/block input
- [ ] Implement mulligan input (keep/mulligan)
- [ ] Tests: Input parsing, validation

**4.3 Error Messages**
- [ ] Implement friendly error messages
- [ ] Show why action is illegal
- [ ] Suggest legal alternatives
- [ ] Tests: Error message quality

**4.4 Game Loop Integration**
- [ ] Integrate UI into game loop
- [ ] Display state after each player action
- [ ] Prompt for next action
- [ ] Handle game end (display winner)
- [ ] Tests: Full game playability

**4.5 Mulligan System**
- [ ] Display opening hand
- [ ] Allow keep/mulligan decision
- [ ] Handle mulligan (redraw to 6, etc.)
- [ ] Up to 3 mulligans (or configurable)
- [ ] Tests: Mulligan rules

### Deliverables:
- ✅ Functional CLI for game state display
- ✅ Working command parser for player actions
- ✅ Friendly error messages
- ✅ Playable goldfisch mode (single player vs. nothing)
- ✅ Mulligan system

### Success Criteria:
- Can play complete 10-turn game via CLI
- All player actions work correctly
- UI is readable and intuitive
- Errors are helpful

---

## PHASE 5: Multiplayer Support (Weeks 9-10)

**Goal**: Enable two human players to play against each other

### Tasks:

**5.1 Two-Player Game State**
- [ ] Extend GameState to support 2 players
- [ ] Implement turn progression with 2 players
- [ ] Implement active_player tracking
- [ ] Implement priority tracking for 2 players
- [ ] Tests: 2-player state management

**5.2 Priority & Response System**
- [ ] Implement priority passing between players
- [ ] Implement "can you respond?" prompts
- [ ] Implement response window (timeout or waiting for input)
- [ ] Implement priority reset after stack resolves
- [ ] Tests: Priority flow with 2 players

**5.3 Concurrent Triggered Abilities**
- [ ] Implement simultaneous triggers from both players
- [ ] Active player orders their triggers first (RULE 607.1)
- [ ] Non-active player orders their triggers after
- [ ] Stack triggers in correct order
- [ ] Tests: Multiple simultaneous triggers

**5.4 Turn Time Limits**
- [ ] Implement turn timer (optional, e.g., 5 minutes per turn)
- [ ] Warn player when time running low
- [ ] Auto-pass if time runs out
- [ ] Tests: Timer functionality

**5.5 Game Logging**
- [ ] Log all actions (move to graveyard, cast spell, etc.)
- [ ] Log all triggers/resolutions
- [ ] Log life total changes
- [ ] Enable replay of game
- [ ] Tests: Log correctness

**5.6 UI for Two Players**
- [ ] Show both player info (not both hands!)
- [ ] Show whose turn it is
- [ ] Show whose priority it is
- [ ] Show prompts for current player ("Your turn" vs. "Waiting for opponent...")
- [ ] Tests: UI clarity

### Deliverables:
- ✅ 2-player game state and turn progression
- ✅ Priority system for 2 players
- ✅ Concurrent trigger handling
- ✅ Turn timer (optional)
- ✅ Game logging/replay
- ✅ 2-player UI

### Success Criteria:
- Can play complete 2-player game
- Priority works correctly
- Simultaneous triggers are handled correctly
- Game is logged and can be reviewed

---

## PHASE 6: LLM-Powered Deck Analysis (Weeks 11-12)

**Goal**: Enable UC2 - LLM analyzes decks for strategy/synergies

### Tasks:

**6.1 LLM API Integration**
- [ ] Set up Claude API client (or GPT, etc.)
- [ ] Implement API authentication
- [ ] Implement error handling for API failures
- [ ] Implement retry logic
- [ ] Tests: API calls work

**6.2 Deck Formatter for LLM**
- [ ] Format deck into readable text for LLM
- [ ] Group by card type
- [ ] Show mana costs, abilities
- [ ] Make it easy for LLM to parse
- [ ] Tests: Formatter output quality

**6.3 Prompt Engineering**
- [ ] Create prompt template for deck analysis
- [ ] Request: Win conditions, archetype, synergies, issues, score
- [ ] Request structured JSON output
- [ ] Test prompts with various decks
- [ ] Iterate on prompt clarity
- [ ] Tests: LLM response quality

**6.4 Output Parser**
- [ ] Parse JSON output from LLM
- [ ] Validate required fields
- [ ] Extract win conditions
- [ ] Extract archetype
- [ ] Extract synergies
- [ ] Extract issues
- [ ] Extract scores
- [ ] Tests: Parser correctness

**6.5 Analysis Display**
- [ ] Create report structure
- [ ] Display win conditions and probability
- [ ] Display archetype and purity
- [ ] Display key synergies
- [ ] Display potential issues
- [ ] Display scores
- [ ] Tests: Report readability

**6.6 Caching & Storage**
- [ ] Cache LLM responses (expensive API calls!)
- [ ] Store analysis with deck
- [ ] Allow re-running analysis
- [ ] Tests: Cache hits/misses

### Deliverables:
- ✅ LLM API integration
- ✅ Deck formatter
- ✅ Prompt templates
- ✅ Output parser
- ✅ Deck analysis report
- ✅ Response caching

### Success Criteria:
- Can analyze deck via LLM
- Analysis is insightful and accurate
- API calls are cached (not wasteful)
- Report is readable

---

## PHASE 7: Bot Automation (Weeks 13-14)

**Goal**: Enable UC5 - Automate player turns with AI

### Tasks:

**7.1 Action Evaluator**
- [ ] Implement scoring for different action types
  - [ ] Win condition spells (high score)
  - [ ] Removal vs. threats (medium-high score)
  - [ ] Draw/mana acceleration (medium score)
  - [ ] Generic spells (low score)
- [ ] Implement threat assessment (opponent dangers)
- [ ] Implement board evaluation (my threats)
- [ ] Tests: Scores are reasonable

**7.2 Strategy Engine**
- [ ] Detect deck archetype (from LLM analysis or heuristics)
- [ ] Define action priorities per archetype:
  - [ ] Aggro: Attack > Play threats > Pass
  - [ ] Control: Remove threats > Draw > Play finisher > Pass
  - [ ] Combo: Play combo pieces > Play tutors > Pass
  - [ ] Ramp: Play acceleration > Play threats > Pass
- [ ] Implement strategy selection
- [ ] Tests: Strategy detection

**7.3 Decision Maker**
- [ ] Implement turn decision loop
  - [ ] Get legal actions for current player
  - [ ] Score each action
  - [ ] Return highest-scoring action
- [ ] Loop until player passes (main phase end)
- [ ] Implement attack/block decisions
- [ ] Tests: Bot makes reasonable decisions

**7.4 Bot Play AI**
- [ ] Basic Greedy strategy (highest score wins)
- [ ] Handle tie-breaking (multiple same-score actions)
- [ ] Combat AI (which creatures to attack with? Attack where?)
- [ ] Mulligan AI (heuristic: keep if playable spells + mana)
- [ ] Implement "bot thinking" display (what's the bot doing?)
- [ ] Tests: Bot plays reasonable games

**7.5 Game Mode: Bot vs. Bot**
- [ ] Enable two bot players to play each other
- [ ] Implement auto-play (no human input)
- [ ] Log all bot decisions
- [ ] Implement game end detection
- [ ] Tests: Bot vs. bot games complete

**7.6 Game Mode: Human vs. Bot**
- [ ] Enable human player vs. bot
- [ ] Implement turn selection (who plays: human or bot?)
- [ ] Implement player switching
- [ ] Tests: Human can play vs. bot

**7.7 Game Mode: Human vs. Human with Bot Assist**
- [ ] Enable human players with optional bot suggestions
- [ ] Bot suggests best move (don't force it)
- [ ] Implement "hint" command
- [ ] Tests: Suggestions are helpful

### Deliverables:
- ✅ Action evaluator with scoring
- ✅ Strategy engine per archetype
- ✅ Bot decision maker
- ✅ Working bot AI
- ✅ Bot vs. Bot game mode
- ✅ Human vs. Bot game mode
- ✅ Bot suggestions/hints

### Success Criteria:
- Bot makes reasonable decisions
- Can play complete bot vs. bot game
- Human can play vs. bot
- Suggestions are helpful and non-intrusive

---

# PART 5: DEPENDENCIES GRAPH

```
PHASE 1: Data Layer
  ├─ Card DB + Parser
  ├─ Game State Models
  └─ (Dependency for all other phases)
         ↓
PHASE 2: Rules Engine
  ├─ Casting, Stack, Mana, Priority, Triggered Abilities
  ├─ Card Effect Services
  └─ (Dependency for Phase 3-7)
         ↓
         ├────────────────────────────────────────┐
         ↓                                        ↓
PHASE 3: Game Loop          PHASE 6: LLM Analysis
  ├─ Turn/Phase Manager           ├─ LLM Integration
  ├─ Combat Resolver              ├─ Deck Formatter
  ├─ State-Based Actions          ├─ Prompt Engineering
  ├─ Action Validator             └─ Output Parser
  ├─ Event Bus                     (Can run parallel after Phase 1)
  └─ (Dependency for Phase 4-5-7)
         ↓
         ├─────────────┬──────────────┐
         ↓             ↓              ↓
PHASE 4: UI       PHASE 5: Multiplayer    PHASE 7: Bot AI
├─ CLI Display       ├─ 2-Player State        ├─ Action Evaluator
├─ Input Handler     ├─ Priority System       ├─ Strategy Engine
├─ Error Messages    ├─ Concurrent Triggers   ├─ Decision Maker
└─ Goldfisch Mode    ├─ Turn Timers           ├─ Bot Strategy
    (Single Player)  ├─ Game Logging          └─ Bot vs. Bot/Human
                     └─ 2-Player UI
```

**Critical Path**: Phase 1 → Phase 2 → Phase 3 → (Phase 4 and/or Phase 5)

**Parallel Paths**:
- Phase 6 (LLM) can start after Phase 1
- Phase 7 (Bot) depends on Phase 2-3

---

# PART 6: SUCCESS CRITERIA

## Phase-by-Phase Acceptance Criteria

### Phase 1: ✅ Data Layer Ready
- [ ] Load any Commander deck
- [ ] Validate against all Commander rules
- [ ] Game state models are tested
- [ ] >95% test pass rate

### Phase 2: ✅ Rules Engine Correct
- [ ] Can cast spells (Instant/Sorcery timing works)
- [ ] Stack resolves LIFO correctly
- [ ] Mana system works (production, payment, colors)
- [ ] Priority system works
- [ ] Triggered abilities fire correctly
- [ ] Card effects work (damage, draw, discard, etc.)
- [ ] >95% test pass rate
- [ ] Rules match MTG Comprehensive Rules

### Phase 3: ✅ Game Loop Works
- [ ] Can play 10 full turns without errors
- [ ] Phases/steps execute correctly
- [ ] Combat works
- [ ] State-based actions work
- [ ] Events trigger at correct times
- [ ] Can integrate manual player actions
- [ ] >95% test pass rate

### Phase 4: ✅ Goldfisch Playable
- [ ] Can play complete game via CLI
- [ ] Display is clear and readable
- [ ] Input parsing works for all commands
- [ ] Error messages are helpful
- [ ] Mulligan system works
- [ ] No crashes during 10-turn game
- [ ] User feedback: "Can play a game!"

### Phase 5: ✅ Multiplayer Works
- [ ] Two human players can play vs. each other
- [ ] Priority system works with 2 players
- [ ] Simultaneous triggers are handled
- [ ] Turn timers work (if implemented)
- [ ] Game logging is correct
- [ ] Can complete 2-player game without errors
- [ ] User feedback: "Just like playing Magic!"

### Phase 6: ✅ LLM Analysis Ready
- [ ] Can send deck to LLM
- [ ] Receive structured analysis
- [ ] Analyze various deck types (Aggro, Control, Combo, etc.)
- [ ] Analysis is accurate (spot-checked manually)
- [ ] Caching works (API not hammered)
- [ ] Report is readable and useful
- [ ] User feedback: "LLM understands my deck!"

### Phase 7: ✅ Bot Automation Ready
- [ ] Bot makes reasonable decisions
- [ ] Can play bot vs. bot game (complete)
- [ ] Can play human vs. bot (complete)
- [ ] Bot strategies vary by archetype
- [ ] Suggestions/hints are helpful
- [ ] No crashes or infinite loops
- [ ] User feedback: "Bot plays like a real player!"

---

# PART 7: TESTING STRATEGY

## Unit Tests (Per Phase)

### Phase 1 Tests:
- Card lookup correctness
- Deckliste parsing (all formats)
- Validation rules (Singleton, Legend, Color Identity, Ban List)
- Game state updates

### Phase 2 Tests:
- RULE 601 (Casting timing for each type)
- RULE 608 (Stack LIFO)
- RULE 504 (Mana production/payment)
- RULE 117 (Priority passing)
- RULE 603/607 (Trigger detection/ordering)
- Card effects (damage, draw, discard, etc.)

### Phase 3 Tests:
- Turn progression
- Phase progression
- Step progression
- Combat rules
- State-based actions
- Event firing
- Action validation

### Phase 4 Tests:
- Display formatting
- Input parsing
- Error messages
- Mulligan logic

### Phase 5 Tests:
- 2-player state
- Priority with 2 players
- Concurrent triggers
- Turn timers
- Game logging

### Phase 6 Tests:
- LLM API calls
- Deck formatting
- Output parsing
- Caching

### Phase 7 Tests:
- Action scoring
- Strategy detection
- Bot decisions
- Combat AI
- Mulligan AI

## Integration Tests

### End-to-End:
- Full 1-player game (10 turns)
- Full 2-player game (10 turns each)
- Bot vs. Bot game (10 turns)
- Human vs. Bot game (10 turns)
- Deck analysis (load deck → LLM analysis → report)

## Validation Tests

### Against Real Magic Rules:
- Scenario: "Player casts Lightning Bolt while opponent has Counterspell"
  - Expected: Counterspell can respond
  - Test: Both players can act per priority rules
- Scenario: "Goblin Electromancer with multiple instants cast"
  - Expected: Goblin gets +1/+2 for each instant
  - Test: Triggered ability fires correctly each time
- Scenario: "Multiple simultaneous triggers"
  - Expected: Active player orders, then resolve
  - Test: Ordering is correct, abilities resolve in order

---

# CONCLUSION

This architecture and build plan:
1. ✅ Addresses all 5 Use Cases (UC1-UC5)
2. ✅ Implements core rules correctly
3. ✅ Enables playable games (UC3-UC5)
4. ✅ Integrates LLM for analysis (UC2)
5. ✅ Progresses logically (Phase 1 → 7)
6. ✅ Has clear success criteria per phase
7. ✅ Includes testing strategy

**Next Step**: Begin Phase 1 (Data Layer).
