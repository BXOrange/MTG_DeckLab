# Magic: The Gathering Deck Analyzer
## Rules-Driven Architecture Plan

---

# PART 1: FOUNDATIONAL UNDERSTANDING

## The Core Insight: Rules Are Specifications

The Magic: The Gathering Comprehensive Rules are **not guidelines** — they are **deterministic specifications** that exactly define:
- Which card types exist and how they behave
- When abilities can trigger or be cast
- How the stack resolves
- The complete ordering of game events

**Therefore:** The architecture is not a design problem — it is a **specification implementation** problem.

Our job is not to "design Priority" or "invent ordering" — our job is to **read the Comprehensive Rules and code them**.

---

## The Regulatory Framework (Relevant Rules)

### RULE 109: CARD TYPES
**Specifies the complete type hierarchy:**
- Artifact
- Enchantment
- Instant
- Land
- Planeswalker
- Sorcery
- Creature
- Battle

These are not "suggestions" — these are the **authoritative categories** that determine how cards behave.

### RULE 601: CASTING SPELLS
**Specifies exactly when/where spells can be cast:**
- RULE 601.2a: "A player may cast a sorcery spell only during the main phase of their turn"
- RULE 601.3a: "A player may cast an instant spell any time they have priority"
- RULE 601.1: "To cast a spell is to take it from where it is (usually the hand) and put it onto the stack"

**This is not design.** This is specification.

### RULE 602: ACTIVATED ABILITIES
**Specifies how activated abilities work:**
- RULE 602.1a: "An activated ability is an ability that can be activated whenever the player who controls it has priority"
- RULE 602.2: "Activated ability is written as `[Cost]: [Effect]`"

### RULE 603: TRIGGERED ABILITIES
**Specifies triggered ability mechanics:**
- RULE 603.1: "Triggered ability triggers when its trigger event occurs"
- RULE 603.2: "Triggered ability is put onto the stack when it triggers"
- RULE 607.1: "If multiple triggered abilities trigger at the same time, the active player puts them on the stack in any order they choose"

### RULE 608: RESOLUTION
**Specifies exactly how the stack resolves:**
- RULE 608.1: "When a spell resolves, the instructions on it are followed"
- RULE 608.2: "When an ability resolves, the effects of the ability are applied"
- RULE 609.1: "Continuously-applied effects are applied in a specific order"

**Stack resolution is LIFO** (Last In, First Out) — not a design choice, a rule specification.

### RULE 504: MANA PAYMENT
**Specifies mana system:**
- RULE 504.2: "A player may use mana in their mana pool only to pay costs"
- RULE 504.3a: "Mana is produced (added to mana pool) when an effect says so"

### RULE 110: PLAYERS
**Specifies player structure:**
- RULE 110.1: "A player is one of the people playing the game"
- RULE 110.2a: "Each player has 20 life"
- RULE 110.3: "The players sit in a circle in the order of play"

### RULE 702: KEYWORD ABILITIES
**Specifies how common abilities work:**
- RULE 702.19a: "Draw: Draw cards"
- RULE 702.32a: "Discard: Put a card from your hand into your graveyard"
- RULE 702.98a: "Scry: A player looks at the top X cards and puts them back in any order"

---

# PART 2: ARCHITECTURE AS RULE IMPLEMENTATION

## Principle: Service Structure Follows Card Type Hierarchy

From RULE 109, card types define behavior. Therefore, services follow card types:

```
RULE 109: Card Types
    ↓
Service Hierarchy
    ↓
Implementation Structure
```

### Service Hierarchy (from RULE 109)

```python
# Base service: All spells/abilities follow these patterns
class CardService:
    """
    Abstract base for any card effect.
    Directly implements how cards interact with game state.
    """
    card: Card
    
    def register(self, event_bus: EventBus, context: GameContext):
        """
        Subclasses implement RULE 601/602/603:
        - When can this be cast?
        - What events trigger this?
        - How does it resolve?
        """
        pass

# RULE 601.3a: "Instant spells can be cast any time player has priority"
class InstantService(CardService):
    """
    Implements RULE 601.3a: Timing has no restrictions.
    Can be cast during opponent's turn.
    Goes on stack immediately upon casting.
    """
    
    def can_cast(self, context: GameContext) -> bool:
        # RULE 601.3a: No timing restrictions
        return context.player_has_priority()
    
    def register(self, event_bus, context):
        # Register for casting
        event_bus.on(
            "PLAYER_CASTS_SPELL",
            self.on_cast,
            condition=lambda: self.card.is_instant(),
            rule="601.3a"  # For documentation
        )
        # Register for resolution
        event_bus.on(
            "SPELL_RESOLVES",
            self.on_resolve,
            source_card=self.card,
            rule="608.1"
        )
    
    def on_cast(self, context):
        """RULE 601: Moving to stack"""
        context.stack.add(self.card)
    
    def on_resolve(self, context):
        """Override in subclass. RULE 608.1: Follow instructions"""
        pass

# RULE 601.2a: "Sorcery spells can be cast only during main phase"
class SorceryService(CardService):
    """
    Implements RULE 601.2a: Timing restricted to main phase.
    Cannot be cast during opponent's turn.
    """
    
    def can_cast(self, context: GameContext) -> bool:
        # RULE 601.2a
        return (context.is_main_phase() and 
                context.is_active_player_turn())
    
    def register(self, event_bus, context):
        event_bus.on(
            "PLAYER_CASTS_SPELL",
            self.on_cast,
            condition=lambda: self.card.is_sorcery(),
            rule="601.2a"
        )
        event_bus.on("SPELL_RESOLVES", self.on_resolve, source_card=self.card)

# RULE 109: Creatures
class CreatureService(CardService):
    """
    Creatures are permanents (RULE 109.2).
    They are not cast to stack, but put directly into play.
    RULE 303.4a: Creatures enter battlefield.
    """
    
    def can_cast(self, context: GameContext) -> bool:
        # RULE 601.2a: Creatures cast as sorceries
        return (context.is_main_phase() and 
                context.is_active_player_turn())
    
    def register(self, event_bus, context):
        # When creature is cast, it will enter battlefield
        event_bus.on(
            "SPELL_RESOLVES",
            self.on_enters_battlefield,
            source_card=self.card,
            rule="303.4"  # Permanents enter battlefield
        )
        # Triggered abilities on creature
        event_bus.on(
            "CREATURE_ENTERS_BATTLEFIELD",
            self.check_etb_trigger,
            source_card=self.card,
            rule="603.1"
        )

# RULE 602: Activated Abilities
class ActivatedAbilityService(CardService):
    """
    Implements RULE 602.1a: Activated ability can be activated 
    whenever controller has priority.
    Format: [Cost]: [Effect]
    """
    
    activation_cost: ManaCost  # or other cost type
    effect: Callable
    
    def can_activate(self, context: GameContext) -> bool:
        # RULE 602.1a
        return (context.player_has_priority() and
                context.can_pay(self.activation_cost))
    
    def register(self, event_bus, context):
        event_bus.on(
            "PLAYER_ACTIVATES_ABILITY",
            self.on_activate,
            source_card=self.card,
            rule="602.1a"
        )

# RULE 603: Triggered Abilities
class TriggeredAbilityService(CardService):
    """
    Implements RULE 603.1: Triggered ability automatically triggers 
    when trigger event occurs.
    RULE 607.1: Ordering is by active player's choice if simultaneous.
    """
    
    trigger_event: str      # "ENTERS_BATTLEFIELD", "SPELL_CAST", etc.
    trigger_condition: Callable  # Additional condition check
    effect: Callable
    
    def register(self, event_bus, context):
        event_bus.on(
            self.trigger_event,
            self.check_and_trigger,
            source_card=self.card,
            rule="603.1"
        )
    
    def check_and_trigger(self, context):
        """RULE 603.1: Check if trigger condition is met"""
        if self.trigger_condition(context):
            # RULE 603.2: Triggered ability goes on stack
            context.stack.add_triggered_ability(self, context)

# RULE 109: Enchantments (simplified for MVP)
class EnchantmentService(CardService):
    """
    Enchantment is permanent. 
    Continuously-applied effects resolve per RULE 609.
    """
    
    def register(self, event_bus, context):
        # Enchantments apply their effects continuously
        event_bus.on(
            "ENCHANTMENT_ENTERS",
            self.on_enters,
            source_card=self.card,
            rule="303.4"
        )
        # Continuous effects apply per RULE 609
        event_bus.on(
            "APPLY_CONTINUOUS_EFFECTS",
            self.apply_effect,
            rule="609.1"
        )
```

---

## Principle 2: Stack Resolution Follows RULE 608

The stack is not "something we design" — RULE 608 specifies exactly how it works.

```python
# RULE 608: RESOLUTION
class Stack:
    """
    Implementation of RULE 608: Stack Resolution.
    
    RULE 608.1: When spell resolves, follow its instructions.
    RULE 608.2: When ability resolves, apply its effects.
    
    Key specification: LIFO (Last In, First Out)
    - Newest item on top
    - Resolves first
    """
    
    items: list[StackItem] = []  # LIFO order
    
    def push(self, item: StackItem):
        """Add to top of stack"""
        self.items.append(item)  # Append = top
    
    def resolve_next(self, context: GameContext):
        """
        RULE 608: Resolve top item.
        After each resolution, check for new triggered abilities.
        """
        if not self.items:
            return
        
        top_item = self.items.pop()  # LIFO: pop from end = last added
        
        # RULE 608.1/608.2: Follow instructions
        top_item.resolve(context)
        
        # RULE 603.2: After resolution, triggered abilities may trigger
        # They will be added to stack by EventBus
    
    def is_empty(self) -> bool:
        return len(self.items) == 0

class StackItem:
    """
    A spell or ability on the stack.
    Can be cast spell or triggered ability.
    """
    source: CardService
    context: GameContext
    resolved: bool = False
    
    def resolve(self, context: GameContext):
        """RULE 608.1: Follow the spell's instructions"""
        self.source.on_resolve(context)
        self.resolved = True
```

**Critical point:** Stack resolution order is not something we choose. RULE 608 specifies it as LIFO. We just code it.

---

## Principle 3: Triggered Ability Ordering Follows RULE 607

Triggered abilities don't have "arbitrary priority" — RULE 607 specifies exactly how they order.

```python
# RULE 607: FOLLOWING ABILITIES
# RULE 607.1: If multiple triggered abilities trigger at same time,
#             active player puts them on stack in any order

class TriggeredAbilityResolver:
    """
    Implementation of RULE 607.1: Ordering simultaneous triggers.
    
    When multiple abilities trigger at the same time:
    1. Find all triggered abilities for this event
    2. Active player chooses order
    3. Push onto stack in that order (RULE 608: LIFO means reverse order)
    """
    
    def resolve_triggers(self, event_type: str, context: GameContext):
        """
        RULE 603.1: Triggered abilities trigger when event occurs.
        RULE 607.1: Order is active player's choice if simultaneous.
        """
        
        # Find all triggered abilities for this event
        triggered = self.find_triggered_abilities(
            event_type=event_type,
            context=context
        )
        
        if not triggered:
            return
        
        # RULE 607.1: Active player orders them
        if len(triggered) > 1:
            ordered = context.active_player.choose_order(triggered)
        else:
            ordered = triggered
        
        # RULE 603.2: Push to stack in order
        # Since stack is LIFO, we reverse: first chosen goes deeper
        for ability in ordered:
            context.stack.push(ability)
    
    def find_triggered_abilities(self, event_type: str, context: GameContext):
        """Find all abilities that trigger on this event"""
        triggered = []
        for permanent in context.battlefield:
            for ability in permanent.triggered_abilities:
                if ability.trigger_event == event_type:
                    if ability.trigger_condition(context):
                        triggered.append(ability)
        return triggered
```

**Again:** No "priority invention". Just RULE 607 coding.

---

## Principle 4: Casting Timing Follows RULE 601

When spells can be cast is not a design choice — RULE 601 specifies it.

```python
# RULE 601: CASTING SPELLS
class CastingValidator:
    """
    Implementation of RULE 601: Determines when spells can be cast.
    
    RULE 601.2a: Sorcery only main phase
    RULE 601.3a: Instant any time
    RULE 601.2: Creature/Enchantment/etc. like sorcery
    """
    
    def can_cast(self, card: Card, context: GameContext) -> bool:
        """Check if spell can be cast right now"""
        
        # First check: Do we have priority?
        if not context.player_has_priority():
            return False
        
        # RULE 601.1: "To cast a spell is to take it from hand and put on stack"
        if card.zone != "HAND":
            return False
        
        # RULE 601.3a: Instant has no timing restriction
        if card.is_instant():
            return True
        
        # RULE 601.2a: Sorcery only main phase
        if card.is_sorcery():
            return context.is_main_phase() and context.is_active_player_turn()
        
        # RULE 601.2: Creature, Enchantment, Battle like sorcery
        if card.type in ["Creature", "Enchantment", "Battle"]:
            return context.is_main_phase() and context.is_active_player_turn()
        
        # Other permanents: like sorcery (conservative default)
        return context.is_main_phase() and context.is_active_player_turn()
```

---

# PART 3: CORE SERVICES (Examples)

Every service is a direct implementation of a rule specification, not a design choice.

## Example 1: Lightning Bolt (Instant)

```python
# Lightning Bolt
# Type: Instant (RULE 601.3a)
# Effect: Deal 3 damage to target creature or player

class LightningBoltService(InstantService):
    """
    Card: Lightning Bolt
    Type: Instant (RULE 601.3a: can be cast any time)
    Effect: Deal 3 damage to target creature or player
    
    Implementation follows:
    - RULE 601.3a (when can be cast)
    - RULE 608.1 (what happens when resolves)
    """
    
    def on_resolve(self, context: GameContext):
        """
        RULE 608.1: When spell resolves, follow its instructions.
        
        Lightning Bolt instructions:
        1. Player chooses target (creature or player)
        2. Deal 3 damage to that target
        """
        
        # Targets are chosen by player during casting
        target = context.get_chosen_target()
        
        if target is None or target.is_illegal(context):
            # Target became illegal, spell fizzles (RULE 608.2c)
            return
        
        # Deal damage (RULE 119: Damage)
        context.deal_damage(target, amount=3)
```

## Example 2: Counterspell (Instant)

```python
# Counterspell
# Type: Instant (RULE 601.3a)
# Effect: Counter target spell

class CounterspellService(InstantService):
    """
    Card: Counterspell
    Type: Instant (RULE 601.3a: can be cast any time)
    Effect: Counter target spell
    
    Implementation follows:
    - RULE 601.3a (timing)
    - RULE 608.1 (resolution)
    - RULE 116: Countering (prevents spell from resolving)
    """
    
    def on_resolve(self, context: GameContext):
        """RULE 608.1: Follow instructions"""
        
        target_spell = context.get_chosen_target()
        
        if target_spell is None or not target_spell.is_spell():
            # Target invalid, fizzle
            return
        
        # RULE 116.1: Counter the spell
        # This removes it from stack, prevents resolution
        context.stack.remove(target_spell)
        target_spell.move_to_graveyard()
```

## Example 3: Goblin Electromancer (Creature with Triggered Ability)

```python
# Goblin Electromancer
# Type: Creature (RULE 601.2a: like sorcery)
# Triggered Ability: Whenever you cast instant or sorcery, +1/+2

class GoblinElectromancerService(CreatureService):
    """
    Card: Goblin Electromancer
    Type: Creature (2/2 for 1R)
    Triggered Ability: Whenever you cast an instant or sorcery spell,
                       Goblin Electromancer gets +1/+2 until end of turn
    
    Implementation follows:
    - RULE 601.2a (creature can be cast like sorcery)
    - RULE 303.4 (enters battlefield as permanent)
    - RULE 603 (triggered ability)
    """
    
    def register(self, event_bus, context):
        super().register(event_bus, context)
        
        # RULE 603.1: Triggered ability triggers on event
        event_bus.on(
            "SPELL_CAST",
            self.check_trigger,
            source_card=self.card,
            rule="603.1"
        )
    
    def check_trigger(self, context: GameContext):
        """
        RULE 603.1: Trigger condition check
        - Last cast spell is instant or sorcery
        - This ability triggers
        """
        last_spell = context.last_cast_spell
        
        if not last_spell:
            return
        
        if last_spell.is_instant_or_sorcery():
            # RULE 603.2: Triggered ability goes on stack
            self.pump_effect = TriggeredAbilityPump(
                source=self.card,
                power_boost=1,
                toughness_boost=2,
                duration="end_of_turn"
            )
            context.stack.push(self.pump_effect)
    
    def on_enters_battlefield(self, context):
        """Creature enters play"""
        context.add_to_battlefield(self.card)
        # ETB triggers are handled separately
```

## Example 4: Demonic Tutor (Sorcery with Search Effect)

```python
# Demonic Tutor
# Type: Sorcery (RULE 601.2a)
# Effect: Search library for a card, add to hand, shuffle

class DemonicTutorService(SorceryService):
    """
    Card: Demonic Tutor
    Type: Sorcery (RULE 601.2a: main phase only)
    Effect: Search library for card, add to hand, shuffle
    
    Implementation follows:
    - RULE 601.2a (timing: sorcery)
    - RULE 608.1 (resolution: search and shuffle)
    """
    
    def on_resolve(self, context: GameContext):
        """RULE 608.1: Follow instructions"""
        
        # Player searches library (custom logic: AI chooses)
        card_to_search = context.ai_choose_card_from_deck(
            selection_criteria=self.get_best_card
        )
        
        # Add to hand
        context.add_to_hand(card_to_search)
        
        # Shuffle library
        context.shuffle_library()
    
    def get_best_card(self, deck: List[Card], context: GameContext) -> Card:
        """
        AI logic: Choose best card to tutor.
        This is simulation-specific, not rule-specific.
        """
        # For MVP: Tutor win conditions or mana acceleration
        win_conditions = [c for c in deck if c.is_win_condition()]
        if win_conditions:
            return max(win_conditions, key=lambda c: c.power)
        
        # Fallback to mana
        mana_accelerators = [c for c in deck if c.produces_mana()]
        if mana_accelerators:
            return mana_accelerators[0]
        
        return deck[0]
```

---

# PART 4: IMPLEMENTATION PHASES

## Phase 1: Rules Infrastructure (Weeks 1-2)

**Goal:** Implement the foundational ruleset that everything else depends on.

These are not "design choices" — these are direct implementations of the Comprehensive Rules.

### Phase 1.1: Card Type Hierarchy

**Deliverable:** Service base classes matching RULE 109

```
Tasks:
1. Create CardService abstract base
   - Implements common behavior (casting, resolution)
   - RULE 601: When can be cast
   - RULE 608: How resolution works
   
2. Create InstantService (RULE 601.3a)
   - No timing restrictions
   - Can be cast any time player has priority
   
3. Create SorceryService (RULE 601.2a)
   - Main phase only
   - Active player's turn only
   
4. Create CreatureService (RULE 601.2)
   - Like sorcery
   - Permanents (RULE 110.4)
   
5. Create TriggeredAbilityService (RULE 603)
   - Auto-trigger on event
   - Goes on stack (RULE 603.2)
   
6. Create ActivatedAbilityService (RULE 602)
   - Can be activated when player has priority
   - Costs must be paid
   
7. Create EnchantmentService (RULE 109)
   - Permanents
   - Continuous effects (RULE 609)
```

**Tests:**
- Can cast instant on opponent's turn ✓
- Cannot cast sorcery on opponent's turn ✓
- Triggered ability fires when condition met ✓
- Activated ability requires priority ✓

### Phase 1.2: Stack Implementation (RULE 608)

**Deliverable:** Stack class following RULE 608 exactly

```
Tasks:
1. Implement Stack class
   - LIFO data structure (RULE 608)
   - push() adds item to top
   - resolve_next() takes from top
   
2. Implement StackItem interface
   - Generic representation of spells/abilities
   - source_card, context, resolved status
   
3. Implement resolution order
   - RULE 608.1: Spells resolve in LIFO order
   - RULE 608.2: Abilities resolve after spells
   
4. Implement stack removal (RULE 116: Countering)
   - Countered spells go to graveyard
   - Don't resolve
```

**Tests:**
- LIFO order (last added resolves first) ✓
- Counter removes from stack ✓
- Resolution follows instructions ✓
- Stack is empty after all items resolve ✓

### Phase 1.3: Triggered Ability Ordering (RULE 607)

**Deliverable:** Triggered ability resolver following RULE 607.1

```
Tasks:
1. Implement TriggeredAbilityResolver
   - Finds all abilities that trigger on event
   - Active player chooses order (RULE 607.1)
   - Pushes to stack in order
   
2. Implement simultaneous resolution
   - When multiple abilities trigger at same time
   - Active player orders them
   
3. Implement trigger checking
   - Check if ability's condition is met
   - Only trigger if true
```

**Tests:**
- Multiple triggers in active player's order ✓
- Triggers only fire if condition met ✓
- Ordering affects stack resolution ✓

### Phase 1.4: Game State Foundation

**Deliverable:** GameState tracking per RULE 110 and others

```
Tasks:
1. Implement Player class (RULE 110)
   - Life total (default 20)
   - Library (deck)
   - Hand
   - Graveyard
   - Battlefield
   
2. Implement GameContext
   - Current phase (RULE 500)
   - Current player
   - Priority holder
   - Stack reference
   - Battlefield reference
   
3. Implement Zone management
   - Hand, Library, Graveyard, Battlefield, Stack, Exile
   - Moving cards between zones
   
4. Implement Turn structure (RULE 500)
   - Beginning phase
   - Main phase I
   - Combat phase
   - Main phase II
   - Ending phase
```

**Tests:**
- Player starts with 20 life ✓
- Cards can move between zones ✓
- Phases progress in order ✓

### Phase 1.5: Mana System (RULE 504)

**Deliverable:** Mana management following RULE 504

```
Tasks:
1. Implement Mana class
   - Stores mana by color (W, U, B, R, G, C)
   - Mana pool tracking
   
2. Implement mana production (RULE 504.3)
   - Tap land for mana
   - Add to mana pool
   
3. Implement mana payment (RULE 504.2)
   - Pay costs with mana pool
   - Validate sufficient mana
   
4. Implement casting cost check
   - Verify player can pay spell's cost
   - Color requirements matter
```

**Tests:**
- Tapping land produces mana ✓
- Insufficient mana prevents casting ✓
- Color requirements validated ✓
- Mana pool empties at end of phase ✓

---

## Phase 2: Event Bus (Weeks 3-4)

**Goal:** Central event system that services register with.

This is NOT "designing an event system" — this is implementing how the game communicates rule events.

### Tasks:
```
1. Implement EventBus class
   - on(event_type, callback) register
   - emit(event_type, context) fire
   - Keeps listener order (for stack resolution)
   
2. Implement event types
   - PLAYER_CASTS_SPELL
   - SPELL_RESOLVES
   - CREATURE_ENTERS_BATTLEFIELD
   - TRIGGERED_ABILITY_TRIGGERS
   - And ~15 more core events
   
3. Implement event ordering
   - Some events have defined order (rules)
   - Some are player-chosen (RULE 607)
   
4. Implement context passing
   - Events pass GameContext to services
   - Services can read/modify state
```

**Tests:**
- Events fire in correct order ✓
- Services receive event context ✓
- Multiple listeners handle same event ✓

---

## Phase 3: Core Card Services (Weeks 5-6)

**Goal:** Implement services for ~20 common card effects.

Each service is a direct implementation of a card's rules text.

### Instant Services:
```
1. LightningBolt: Deal 3 damage
2. Counterspell: Counter target spell
3. Spell Pierce: Counter target spell (with cost)
4. Draw Service (Opt, Consider): Draw 1 card
5. Discard Service: Discard 1 card
```

### Sorcery Services:
```
1. Tutor Service (Demonic Tutor): Search library
2. Board Wipe Service (Wrath of God): Destroy creatures
3. Draw Service (Divination): Draw cards
4. Ramp Service (Cultivate): Search lands
```

### Creature Services:
```
1. Basic Creature: 2/2 for 2R
2. GoblinElectromancer: +1/+2 per instant/sorcery
3. Mulldrifter: 2/2 flying, draw on ETB
4. Snapcaster Mage: Flashback with creature
5. More as needed
```

### Enchantment Services:
```
1. Draw Engine: Draw when spell cast
2. Ramp Engine: Produce mana
3. Pump Aura: +2/+2 to creature
```

### Special Services:
```
1. Land Service: Produce mana when tapped
2. Mana Accelerant: Produce multiple mana
```

**For each service:**
- Implement on_resolve() with exact effect
- Register for correct events
- Handle targeting logic
- Test against known behavior

---

## Phase 4: Game Simulator (Weeks 7-8)

**Goal:** 10-turn game simulation with mulligan logic.

This is where rules knowledge + AI decision-making combines.

### Tasks:
```
1. Implement turn structure
   - Beginning phase (draw)
   - Main phase I
   - Combat phase (skip)
   - Main phase II
   - Ending phase
   
2. Implement mulligan logic
   - Heuristic: hand is keepable?
   - Based on mana curve, playables, etc.
   
3. Implement play AI
   - Greedy: play best available spell
   - No lookahead (too slow)
   
4. Implement game loop
   - Run 1000 full games
   - Record metrics for each turn
   - Return aggregated results
```

**Tests:**
- Game runs 10 turns without errors ✓
- Mulligan logic makes reasonable decisions ✓
- Spells cast in legal order ✓
- Stack resolves correctly ✓

---

## Phase 5: Analysis Engine (Weeks 9-10)

**Goal:** Consistency scoring + strategy validation.

### Tasks:
```
1. Implement Consistency Analyzer
   - Calculate hypergeometric probability
   - "Chance to have win condition by turn N"
   - Score 0-100
   
2. Implement Strategy Detector
   - Identify archetype (aggro, control, etc.)
   - Score 0-100
   
3. Implement Mismatch Detector
   - Does deck match its strategy?
   - Find outliers
   
4. Implement Card Importance
   - Which cards matter most?
   - Remove card → how much does consistency drop?
```

---

## Phase 6: Integration & CLI (Weeks 11-12)

**Goal:** Working command-line tool.

### Tasks:
```
1. CLI argument parsing
   - Input: deck.txt
   - Options: --iterations, --format, --depth
   
2. Report generation
   - Text format
   - JSON format
   - HTML format (optional)
   
3. Performance optimization
   - Aim for <5 seconds per deck
   - 1000+ simulations per second
   
4. Documentation
   - Architecture guide
   - How to add new services
   - Testing guide
```

---

# PART 5: SERVICE REGISTRY & DYNAMIC LOADING

Because services are decoupled from core engine, we can load them dynamically:

```python
class ServiceRegistry:
    """
    Load card services based on card data.
    No hardcoding of individual cards.
    """
    
    services: dict[str, Type[CardService]] = {}
    
    @classmethod
    def register_service(cls, card_name: str, service_class: Type[CardService]):
        """Register a service for a card"""
        cls.services[card_name] = service_class
    
    @classmethod
    def load_service(cls, card: Card) -> CardService:
        """Load service for a card"""
        
        # First check: registered service?
        if card.name in cls.services:
            return cls.services[card.name](card)
        
        # Second check: generic service by type?
        if card.is_instant():
            return GenericInstantService(card)
        elif card.is_sorcery():
            return GenericSorceryService(card)
        elif card.is_creature():
            return GenericCreatureService(card)
        
        # Fallback: no service (can't cast)
        return NoOpService(card)

# Registration happens once, at startup:
ServiceRegistry.register_service("Lightning Bolt", LightningBoltService)
ServiceRegistry.register_service("Counterspell", CounterspellService)
ServiceRegistry.register_service("Demonic Tutor", DemonicTutorService)
# ... and so on
```

**Benefit:** Adding a new card doesn't require engine changes. Just add a new service.

---

# PART 6: DIRECTORY STRUCTURE

```
mtg-analyzer/
├── rules/
│   ├── __init__.py
│   ├── comprehensive_rules.py    # Rule constants (RULE 601.2a, etc.)
│   └── rule_mappings.txt          # Where each rule is implemented
│
├── models/
│   ├── __init__.py
│   ├── card.py                   # Card, Zone, Type definitions
│   ├── game_state.py             # GameContext, Player, Battlefield
│   ├── mana.py                   # Mana system (RULE 504)
│   └── stack.py                  # Stack (RULE 608)
│
├── services/
│   ├── __init__.py
│   ├── base.py                   # CardService abstract base
│   ├── card_types.py             # InstantService, SorceryService, etc.
│   ├── abilities.py              # TriggeredAbilityService, ActivatedAbilityService
│   ├── core/
│   │   ├── lightning_bolt.py
│   │   ├── counterspell.py
│   │   ├── demonic_tutor.py
│   │   ├── goblin_electromancer.py
│   │   └── ... (other core services)
│   └── registry.py               # ServiceRegistry for dynamic loading
│
├── engine/
│   ├── __init__.py
│   ├── event_bus.py              # EventBus (event coordination)
│   ├── triggered_resolver.py     # RULE 607: Triggered ability ordering
│   ├── casting_validator.py      # RULE 601: Casting timing
│   └── mana_system.py            # RULE 504: Mana handling
│
├── simulator/
│   ├── __init__.py
│   ├── game_loop.py              # Turn progression, spell casting
│   ├── mulligan_logic.py         # Hand evaluation
│   ├── play_ai.py                # Greedy AI for spell selection
│   └── stats_recorder.py         # Record turn-by-turn metrics
│
├── analysis/
│   ├── __init__.py
│   ├── consistency_analyzer.py   # Probability calculations
│   ├── strategy_analyzer.py      # Archetype detection
│   ├── mismatch_detector.py      # Strategy cohesion
│   └── sensitivity_analyzer.py   # Card importance
│
├── cli/
│   ├── __init__.py
│   ├── main.py                   # CLI entry point
│   ├── report_generator.py       # Text/JSON/HTML reports
│   └── parser.py                 # Decklisten parser
│
├── data/
│   ├── scryfall_cache.json       # Card cache from Scryfall API
│   └── card_effects.yaml         # Card → Service mapping
│
└── tests/
    ├── test_stack.py
    ├── test_casting.py
    ├── test_triggered_abilities.py
    ├── test_services.py
    └── test_full_game.py
```

---

# PART 7: TESTING STRATEGY

### Pyramid Approach:

**Unit Tests (Bottom Layer)**
- Test individual services
- Test CardService.on_resolve() implementations
- Test RULE 601/602/603 implementations

**Integration Tests (Middle Layer)**
- Test CardService + EventBus
- Test Stack resolution
- Test Triggered ability ordering (RULE 607)

**End-to-End Tests (Top Layer)**
- Full 10-turn game simulation
- Known deck validation
- Compare vs. real win rates (when available)

### Rule Compliance Tests:

```python
def test_rule_601_3a_instant_timing():
    """RULE 601.3a: Instant can be cast any time"""
    context = setup_game()
    instant = Card("Lightning Bolt")
    
    # Opponent's turn
    context.active_player = opponent
    
    assert CastingValidator.can_cast(instant, context) == True

def test_rule_608_lifo_stack():
    """RULE 608: Stack resolves LIFO"""
    context = setup_game()
    
    context.cast_spell("Lightning Bolt")  # Added first
    context.cast_spell("Counterspell")    # Added second
    
    # Counterspell resolves first (LIFO)
    next_item = context.stack.resolve_next()
    assert next_item.source.card.name == "Counterspell"
```

---

# PART 8: KEY DIFFERENCES FROM TRADITIONAL ARCHITECTURE

| Aspect | Traditional | Rules-Driven |
|--------|-----------|--------------|
| **Source of Truth** | Architecture design | MTG Comprehensive Rules |
| **Priority System** | Invented numbers (0-100) | RULE 607.1 (player choice) |
| **Stack Ordering** | "Design a priority system" | RULE 608 (LIFO) |
| **Service Structure** | Abstract design | Card type hierarchy (RULE 109) |
| **Validation** | "Does our design work?" | "Does code match rulebook?" |
| **Scalability** | Limited by design | Unlimited (rules specify everything) |
| **New Cards** | Might require engine changes | Just add new service |

---

# PART 9: CRITICAL PATHS

### Blocking Dependencies:

```
Phase 1: Rules Infrastructure
  ↓
  ├─ Phase 2: EventBus
  │   ↓
  │   ├─ Phase 3: Card Services
  │   │   ↓
  │   │   ├─ Phase 4: Game Simulator
  │   │   │   ↓
  │   │   │   └─ Phase 5: Analysis
  │   │   │       ↓
  │   │   │       └─ Phase 6: CLI
```

Phase 1 blocks everything else. Cannot start Phase 2 before Phase 1 complete.

---

# PART 10: SUCCESS METRICS

After 12 weeks:

| Metric | Target | Pass/Fail |
|--------|--------|-----------|
| Stack resolution correct | RULE 608 implemented | |
| Triggered ability ordering | RULE 607 implemented | |
| Casting timing | RULE 601 implemented | |
| 10 full games/second | Performance benchmark | |
| 95%+ rule compliance | Against test suite | |
| Known deck validation | 9/10 decks correct | |
| CLI works end-to-end | One command analysis | |

---

# CONCLUSION

This architecture is not "designed" — it is **specified by the Comprehensive Rules**.

Our job is to:
1. Read the rules
2. Code them directly
3. Test against the rules
4. Extend by adding services (not changing engine)

The result is a system that is **normative** (follows authoritative specifications) rather than **prescriptive** (makes up its own rules).

This makes it maintainable, extensible, and correct by design.
