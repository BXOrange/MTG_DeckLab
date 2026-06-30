# MTG Deck Analyzer: Game Loop, Phases, & Effect System (CRITICAL)

---

# CRITICAL INSIGHT: Rules Are Mutable by Cards

The fundamental truth that breaks most MTG implementations:

**Cards don't just do things. Cards CHANGE THE RULES.**

Examples:
- "Skip your next untap step" → Changes phase execution
- "If you would draw a card, draw two instead" → Overrides draw rule
- "You can't lose the game" → Overrides loss condition
- "Replace that event with this one" → Replacement effect chain

This requires an architecture where:
1. Rules are **definable/overrideable**, not hardcoded
2. Effects can **stack and combine**
3. Effects are **reorderable** (RULE 616: Replacement Effects order)
4. Cards **register** themselves into the system dynamically

---

# PART 1: PHASES & STEPS AS EXECUTABLE SEQUENCES (Not Hardcoded)

## Bad Approach (Don't Do This)

```python
def play_turn(player):
    # Hardcoded phase sequence
    untap_step(player)
    upkeep_step(player)
    draw_step(player)
    main_phase_1(player)
    combat_phase(player)
    main_phase_2(player)
    end_step(player)
    
    # Problem: If card says "skip untap", must add special case
    # If card modifies phase order, code breaks
    # Each new effect type needs new code
```

## Good Approach: Sequence-Based Phase Engine

```python
class GamePhase:
    """A phase/step is a named executable sequence"""
    name: str                           # "untap", "draw", "main1"
    order: int                          # 1, 2, 3...
    effect_points: list[str]            # When can things happen?
    
    # Hooks where effects can apply
    hooks = {
        "beginning": lambda: fire_event("PHASE_BEGIN"),
        "body": lambda: execute_phase_body(),
        "ending": lambda: fire_event("PHASE_END")
    }

class TurnSequence:
    """Ordered list of phases/steps for a turn"""
    phases: list[GamePhase] = [
        GamePhase("beginning", order=0),
        GamePhase("untap", order=1),
        GamePhase("upkeep", order=2),
        GamePhase("draw", order=3),
        GamePhase("main1", order=4),
        GamePhase("combat", order=5),
        GamePhase("main2", order=6),
        GamePhase("ending", order=7)
    ]
    
    def execute_turn(self, player: Player, game_state: GameState):
        """Execute turn by running each phase in order"""
        
        for phase in self.phases:
            # Hook 1: Before phase begins
            game_state.fire_event("BEFORE_PHASE", {"phase": phase})
            
            # Apply effects that modify this phase
            # (e.g., "skip this phase")
            if should_skip_phase(phase, player):
                continue
            
            # Hook 2: Phase body
            execute_phase_body(phase, player)
            
            # Hook 3: After phase ends
            game_state.fire_event("AFTER_PHASE", {"phase": phase})

def should_skip_phase(phase: GamePhase, player: Player) -> bool:
    """Check: Does player have effects that skip this phase?"""
    
    skip_effects = player.get_effects_of_type("SkipPhase")
    
    for effect in skip_effects:
        if effect.target_phase == phase.name:
            return True  # Skip this phase
    
    return False
```

## RULE 500: Proper Phase Structure (Programmatically)

```python
# RULE 500: A turn consists of at most nine steps
# (RULE 501-507: Step details)

TURN_STRUCTURE = {
    "beginning_phase": [
        {"step": "untap", "rule": "501"},      # RULE 501: Untap step
        {"step": "upkeep", "rule": "502"},     # RULE 502: Upkeep step
        {"step": "draw", "rule": "503"}        # RULE 503: Draw step
    ],
    "main_phase": [
        {"step": "main1", "rule": "504"}       # RULE 504: Main phase
    ],
    "combat_phase": [
        {"step": "declare_attackers", "rule": "506.1"},
        {"step": "declare_blockers", "rule": "506.2"},
        {"step": "combat_damage", "rule": "510"}
    ],
    "main_phase2": [
        {"step": "main2", "rule": "504"}
    ],
    "ending_phase": [
        {"step": "ending", "rule": "507"},     # RULE 507: Ending phase
        {"step": "cleanup", "rule": "507.2"}   # RULE 507.2: Cleanup step
    ]
}

# Execute in order:
for phase_name in ["beginning_phase", "main_phase", "combat_phase", "main_phase2", "ending_phase"]:
    for step in TURN_STRUCTURE[phase_name]:
        if not should_skip(step["step"]):
            execute_step(step["step"])
```

---

# PART 2: EFFECT TYPE HIERARCHY

## Four Types of Effects

```python
from abc import ABC, abstractmethod

class GameEffect(ABC):
    """Base class for all effects"""
    source_card: Card
    
    @abstractmethod
    def apply(self, context: GameContext):
        """Apply this effect to game state"""
        pass
    
    @abstractmethod
    def can_apply(self, context: GameContext) -> bool:
        """Check: Can this effect apply right now?"""
        pass

# ============================================================================
# TYPE 1: STATIC EFFECTS
# ============================================================================
# Effects that apply continuously, modifying the game state
# Example: "Creatures you control get +1/+1"
# RULE 611: Continuous effects

class StaticEffect(GameEffect):
    """
    Applies continuously during the game.
    Examples:
      - Aura: "+1/+1 to enchanted creature"
      - Global: "All creatures get +1/+1"
      - Restriction: "Creatures can't attack"
    """
    
    duration: str  # "permanent", "until_end_of_turn", "while_in_hand"
    target: Optional[Card]  # Which permanent does this affect?
    
    def apply(self, context: GameContext):
        """
        Modify game rules/state continuously.
        Called every time state is evaluated (RULE 609).
        """
        if self.target and self.target.type == "creature":
            self.target.power += 1
            self.target.toughness += 1
    
    def end(self):
        """Remove effect (e.g., end of turn)"""
        self.is_active = False

# ============================================================================
# TYPE 2: TRIGGERED ABILITIES
# ============================================================================
# Effects that trigger when condition met, go on stack
# Example: "Whenever you cast a spell, draw a card"
# RULE 603: Triggered abilities

class TriggeredAbility(GameEffect):
    """
    Triggers when condition occurs.
    Goes on stack, can be responded to.
    
    Examples:
      - "Whenever you cast a spell, ..."
      - "When X enters the battlefield, ..."
      - "Whenever a creature dies, ..."
    """
    
    trigger_event: str  # "SPELL_CAST", "CREATURE_ENTERS", etc.
    trigger_condition: Callable  # Additional condition check
    effect: GameEffect  # What happens when triggered?
    optional: bool = False  # "May" vs mandatory
    
    def check_trigger(self, event: GameEvent, context: GameContext) -> bool:
        """
        RULE 603.1: Does this ability trigger now?
        """
        if event.type != self.trigger_event:
            return False
        
        if not self.trigger_condition(context):
            return False
        
        return True
    
    def on_trigger(self, event: GameEvent, context: GameContext):
        """
        RULE 603.2: Triggered ability goes on stack
        """
        context.stack.add_triggered_ability(self, event)

# ============================================================================
# TYPE 3: REPLACEMENT EFFECTS
# ============================================================================
# Effects that REPLACE events instead of triggering
# Example: "If you would draw a card, draw two instead"
# RULE 614: Replacement effects

class ReplacementEffect(GameEffect):
    """
    Replaces an event with a different one.
    DOES NOT go on stack.
    Examples:
      - "If you would draw a card, draw two instead"
      - "If damage would be dealt to you, prevent it"
      - "Instead of discarding, exile"
    """
    
    event_type: str  # "DRAW", "DAMAGE", "DISCARD"
    replacement_fn: Callable  # How to replace the event?
    
    def apply_replacement(self, event: GameEvent, context: GameContext) -> GameEvent:
        """
        RULE 614: Replace event with different event.
        Returns modified event (or None if prevented).
        """
        return self.replacement_fn(event, context)

# ============================================================================
# TYPE 4: ACTIVATED ABILITIES
# ============================================================================
# Effects that player can activate (cost + effect)
# Example: "{T}: Draw a card"
# RULE 602: Activated abilities

class ActivatedAbility(GameEffect):
    """
    Can be activated when conditions met.
    Goes on stack like spell.
    Examples:
      - "{T}: Deal 1 damage"
      - "{2}{U}: Draw a card"
      - "{X}{B}: Tutor"
    """
    
    cost: ManaCost  # What does this cost?
    can_activate: Callable  # When can this be activated?
    effect: GameEffect  # What happens when activated?
    
    def can_activate(self, context: GameContext) -> bool:
        """Check: Can player activate this ability right now?"""
        # Has priority?
        if not context.player_has_priority():
            return False
        
        # Can pay cost?
        if not context.player_can_pay(self.cost):
            return False
        
        return True

# ============================================================================
# SPECIAL: Win/Loss Conditions
# ============================================================================
# Also effects! Can be replaced/prevented by cards
# Example: "You can't lose the game"

class WinConditionEffect(GameEffect):
    """
    Modifies win/loss conditions.
    Examples:
      - "You can't lose"
      - "You win at 10 life (instead of die at 0)"
      - "Draw card = take damage instead"
    """
    
    condition_type: str  # "TAKE_DAMAGE", "LOSE_BY_DRAW", etc.
    override_fn: Callable  # New behavior
    
    def check_condition(self, event: GameEvent, context: GameContext) -> bool:
        """
        Check if this modified win/loss applies.
        Example: "You can't lose" prevents death.
        """
        if event.type == "PLAYER_WOULD_LOSE":
            return False  # Prevent losing
        
        return True
```

---

# PART 3: EFFECT STACKING & RESOLUTION (RULE 616)

## Replacement Effect Ordering (RULE 616)

```python
class ReplacementEffectStack:
    """
    RULE 616: Multiple replacement effects for same event.
    Player chooses order (if active player), else LIFO.
    """
    
    def apply_replacement_effects(
        self,
        event: GameEvent,
        context: GameContext
    ) -> GameEvent:
        """
        Apply all replacement effects to this event.
        Each can modify it further.
        """
        
        # Find all replacement effects for this event
        applicable = self.find_applicable_replacements(event, context)
        
        if not applicable:
            return event  # No replacements
        
        # RULE 616.1: Player chooses order (if active player)
        if len(applicable) > 1:
            ordered = context.active_player.choose_order(applicable)
        else:
            ordered = applicable
        
        # Apply each replacement in order
        current_event = event
        for replacement in ordered:
            # Apply this replacement to the current event
            current_event = replacement.apply_replacement(current_event, context)
            
            if current_event is None:
                # Event was prevented/replaced with nothing
                break
        
        return current_event
    
    def find_applicable_replacements(
        self,
        event: GameEvent,
        context: GameContext
    ) -> list[ReplacementEffect]:
        """Find effects that can replace this event"""
        
        applicable = []
        
        # Check all cards on battlefield (and other zones if relevant)
        for permanent in context.get_all_permanents():
            for effect in permanent.replacement_effects:
                if effect.event_type == event.type:
                    if effect.can_apply(context):
                        applicable.append(effect)
        
        # Also check effects on players
        for player in context.players:
            for effect in player.global_effects:
                if effect.event_type == event.type:
                    applicable.append(effect)
        
        return applicable
```

## Example: Multiple Replacement Effects

```python
# Scenario from actual MTG:
# Player has:
#   1. "If you would draw a card, draw two instead" (Tymna)
#   2. "If you would draw a card, mill instead" (Leyline of the Void)
#   3. You're about to draw a card

# Step 1: Draw event triggered
event = DrawEvent(player=player, count=1)

# Step 2: Find applicable replacements
replacements = [
    TymnaReplacement(),      # Draw 2 instead
    LeylineReplacement()     # Mill instead
]

# Step 3: Player chooses order (RULE 616.1)
# Example: Player chooses [Tymna first, Leyline second]
ordered = [TymnaReplacement(), LeylineReplacement()]

# Step 4: Apply each in order
event = TymnaReplacement.apply(event)     # Draw 1 → Draw 2
# event is now: "Draw 2 cards"

event = LeylineReplacement.apply(event)   # Draw 2 → Mill 2
# event is now: "Mill 2 cards"

# Final: Mill 2 cards (Leyline's replacement took precedence)
# This matches MTG rules (replacement chains)
```

---

# PART 4: CLASS vs. PARAMETER TRADE-OFF (Critical Decision)

## Option A: Class-Based (Rigid, but Type-Safe)

```python
# Each effect type is a class

class DealDamageEffect(GameEffect):
    def __init__(self, source: Card, amount: int, target: any):
        self.source = source
        self.amount = amount
        self.target = target
    
    def apply(self, context):
        context.deal_damage(self.target, self.amount)

class DrawCardEffect(GameEffect):
    def __init__(self, player: Player, count: int):
        self.player = player
        self.count = count
    
    def apply(self, context):
        self.player.draw(self.count)

class DestroyEffect(GameEffect):
    def __init__(self, target: Permanent):
        self.target = target
    
    def apply(self, context):
        context.destroy(self.target)

# Pros:
# - Type-safe, IDE auto-complete
# - Easy to test each effect
# - Clear what parameters each takes
# Cons:
# - Need a class for every effect type
# - Not extensible (need code for new effect types)
# - Hard for cards to create new effect types
```

## Option B: Parameter-Based (Flexible, but Less Type-Safe)

```python
# Generic Effect with parameters

class GenericEffect(GameEffect):
    def __init__(self, effect_type: str, parameters: dict):
        self.effect_type = effect_type
        self.parameters = parameters
    
    def apply(self, context):
        if self.effect_type == "damage":
            context.deal_damage(
                self.parameters["target"],
                self.parameters["amount"]
            )
        elif self.effect_type == "draw":
            context.draw(
                self.parameters["player"],
                self.parameters["count"]
            )
        elif self.effect_type == "destroy":
            context.destroy(self.parameters["target"])
        # ... hundreds more

# Pros:
# - Extensible (add new effect by adding parameter dict)
# - Cards can define effects without code
# Cons:
# - Type errors at runtime
# - No IDE auto-complete
# - Massive if/elif chain
# - Hard to validate parameters
```

## Option C: Hybrid (Best of Both)

```python
# Predefined effect classes, but with generic dispatch

class EffectRegistry:
    """Registry of effect factories"""
    
    _effects = {}
    
    @classmethod
    def register(cls, effect_type: str, factory: Callable):
        """Register a new effect type"""
        cls._effects[effect_type] = factory
    
    @classmethod
    def create(cls, effect_type: str, parameters: dict) -> GameEffect:
        """Create effect from type + parameters"""
        if effect_type not in cls._effects:
            raise ValueError(f"Unknown effect type: {effect_type}")
        
        return cls._effects[effect_type](parameters)

# Register predefined effects
EffectRegistry.register("damage", DealDamageEffect)
EffectRegistry.register("draw", DrawCardEffect)
EffectRegistry.register("destroy", DestroyEffect)
EffectRegistry.register("discard", DiscardEffect)
# ... etc

# Usage (from Card Oracle Text parsing)
class Card:
    def parse_oracle_text(self):
        """Parse oracle text and create effects"""
        
        # "Deal 3 damage to target creature or player"
        self.effects.append(
            EffectRegistry.create("damage", {
                "amount": 3,
                "target": "creature_or_player"
            })
        )
        
        # "Draw a card"
        self.effects.append(
            EffectRegistry.create("draw", {
                "count": 1
            })
        )

# Pros:
# - Extensible (new effects = new class + registration)
# - Type-safe for known effects
# - Cards describe effects parametrically
# - New effect types don't require code change
# Cons:
# - More complex architecture
# - Registration overhead
```

## RECOMMENDATION: Hybrid (Class + Registry)

**Why:**
1. Predefined effects are type-safe
2. New effect types can be added without modifying engine
3. Cards register their effects parametrically
4. Supports both simple and complex effects

---

# PART 5: ORACLE TEXT → AUTOMATIC FUNCTION ASSIGNMENT

## Card Effect Registration (From Card Data)

```python
class Card:
    def __init__(self, card_data: dict):
        self.name = card_data['name']
        self.oracle_text = card_data['oracle_text']
        self.effects = []
        
        # Parse effects from oracle text
        self.register_effects()
    
    def register_effects(self):
        """
        Parse oracle text and register effects.
        Example: "Deal 3 damage to target creature or player"
        → Creates DealDamageEffect(amount=3, target="creature_or_player")
        """
        
        # Use NLP or pattern matching to extract effects
        effects_found = self.parse_oracle_text(self.oracle_text)
        
        for effect_spec in effects_found:
            effect = EffectRegistry.create(
                effect_spec['type'],
                effect_spec['parameters']
            )
            self.effects.append(effect)

def parse_oracle_text(oracle_text: str) -> list[dict]:
    """
    Extract effects from English oracle text.
    
    Examples:
      "Deal 3 damage to target creature or player"
        → {"type": "damage", "amount": 3, "target": "creature_or_player"}
      
      "Draw a card"
        → {"type": "draw", "count": 1}
      
      "Destroy target creature"
        → {"type": "destroy", "target": "creature"}
      
      "Discard your hand, then draw that many cards"
        → [
            {"type": "discard_hand"},
            {"type": "draw", "count": "{hand_size}"}
          ]
    """
    
    # Option 1: Regex patterns (simple cases)
    patterns = [
        (r"Deal (\d+) damage", "damage", {"amount": lambda m: int(m.group(1))}),
        (r"Draw (\d+) cards?", "draw", {"count": lambda m: int(m.group(1))}),
        (r"Destroy target creature", "destroy", {"target": "creature"}),
    ]
    
    effects = []
    
    for pattern, effect_type, param_extractors in patterns:
        matches = re.finditer(pattern, oracle_text)
        for match in matches:
            params = {}
            for key, extractor in param_extractors.items():
                if callable(extractor):
                    params[key] = extractor(match)
                else:
                    params[key] = extractor
            
            effects.append({
                "type": effect_type,
                "parameters": params
            })
    
    # Option 2: LLM-based parsing (more robust, handles edge cases)
    # Use Claude to parse complex oracle text
    llm_parsed = llm_parse_oracle_text(oracle_text)
    effects.extend(llm_parsed)
    
    return effects
```

## LLM-Based Oracle Text Parsing (Robust)

```python
def llm_parse_oracle_text(oracle_text: str, llm_client) -> list[dict]:
    """
    Use Claude to parse complex oracle text.
    More robust than regex, handles edge cases.
    """
    
    prompt = f"""
    Parse this Magic: The Gathering card ability text and return structured effects.
    
    Text: "{oracle_text}"
    
    Return JSON with format:
    {{
      "effects": [
        {{
          "type": "damage|draw|destroy|discard|tutor|counter|...",
          "parameters": {{
            "amount": X,
            "target": "creature|player|spell|...",
            "condition": "...",
            "additional": ...
          }},
          "triggering_condition": "when_cast|etb|when_dies|...",
          "optional": true/false
        }}
      ]
    }}
    
    Be precise about:
    - Effect type (what action)
    - Parameters (amounts, targets, conditions)
    - Triggering condition (if triggered ability)
    - Whether it's optional ("may")
    """
    
    response = llm_client.completion(prompt)
    
    # Parse JSON response
    parsed = json.loads(response)
    
    return parsed['effects']
```

---

# PART 6: SERVICE REGISTRY PATTERN (Scalable)

```python
# services/effect_registry.py

class EffectService(ABC):
    """Base class for effect services"""
    
    @abstractmethod
    def create_effect(self, parameters: dict) -> GameEffect:
        """Create an effect from parameters"""
        pass
    
    @abstractmethod
    def can_parse(self, oracle_text: str) -> bool:
        """Can this service parse this oracle text?"""
        pass

# Core services
class DamageEffectService(EffectService):
    def create_effect(self, params):
        return DealDamageEffect(params['amount'], params['target'])
    
    def can_parse(self, text):
        return "damage" in text.lower()

class DrawEffectService(EffectService):
    def create_effect(self, params):
        return DrawCardEffect(params['count'])
    
    def can_parse(self, text):
        return "draw" in text.lower()

class DestroyEffectService(EffectService):
    def create_effect(self, params):
        return DestroyEffect(params['target'])
    
    def can_parse(self, text):
        return "destroy" in text.lower()

# Registry
class ServiceRegistry:
    services: dict[str, EffectService] = {}
    
    @classmethod
    def register(cls, name: str, service: EffectService):
        cls.services[name] = service
    
    @classmethod
    def get_service(cls, name: str) -> EffectService:
        return cls.services.get(name)
    
    @classmethod
    def create_effect(cls, effect_type: str, params: dict) -> GameEffect:
        service = cls.get_service(effect_type)
        if not service:
            raise ValueError(f"Unknown effect: {effect_type}")
        return service.create_effect(params)

# Initialization
ServiceRegistry.register("damage", DamageEffectService())
ServiceRegistry.register("draw", DrawEffectService())
ServiceRegistry.register("destroy", DestroyEffectService())
# ... add more services

# Usage
card = Card.from_oracle_text("Deal 3 damage to target")
# Card parses: "damage" → DamageEffectService → DealDamageEffect
```

---

# PART 7: COMPLEX SCENARIO: Replacement Effect Chain

## Real MTG Scenario

```
Board State:
- Player A: "If you would draw a card, draw two instead"
- Player B: "If cards would enter graveyard, exile instead"
- Player C: "If you would draw a card, mill one instead"
- Player D: No modifiers
- Player A about to draw 1 card (from Draw step)

What happens?
```

## Execution Trace

```python
# Step 1: Event created
event = DrawEvent(player=player_a, count=1)

# Step 2: Find replacement effects
# Check all permanents for "draw" replacements
replacements_for_draw = [
    Player_A_DoubleDrawReplacement(),    # Draw 2 instead
    Player_C_MillReplacement(),          # Mill instead
]

# Step 3: Order replacements (RULE 616)
# Player A chooses (since they're active player)
# Choice: [Player_A_DoubleDrawReplacement first, then Player_C]

# Step 4: Apply first replacement
# "Draw 1" → "Draw 2" (Player A's effect)
event = DrawEvent(player=player_a, count=2)

# Step 5: Apply second replacement
# Now the question: Does Player C's effect replace "Draw 2"?
# RULE 616.1: YES, replacements can replace previous replacements
# "Draw 2" → "Mill 2" (Player C's effect)
event = MillEvent(player=player_a, count=2)

# Step 6: Resolve final event
# "Mill 2" means put 2 cards from deck to graveyard
cards_to_mill = player_a.library[:2]
for card in cards_to_mill:
    card.move_to(Zone.GRAVEYARD)

# Step 7: After milling, check other replacements
# Player B has "cards in graveyard exile instead"
# Does this apply? Only if another effect makes cards enter graveyard
# (Not automated here, would need another replacement chain)

# Final result: Player A mills 2 cards (not draws them)
```

---

# PART 8: SKIP PHASES (Cards Overriding Rules)

## Scenario: "Skip Your Next Untap Step"

```python
# Card creates this effect:
skip_effect = StaticEffect(
    name="Skip Untap",
    type="SkipPhase",
    target_phase="untap",
    duration="next_turn"
)

# Turn execution:
def execute_turn(player, game_state):
    for phase in TURN_PHASES:
        # Check: Should this phase be skipped?
        if should_skip_phase(phase, player):
            # RULE says: Skip this step
            continue
        
        # Execute phase normally
        execute_phase(phase, player)

def should_skip_phase(phase, player):
    """
    Check all effects on player.
    Any say "skip this phase"?
    """
    skip_effects = player.get_effects_of_type("SkipPhase")
    
    for effect in skip_effects:
        if effect.target_phase == phase.name:
            return True
    
    return False

# Execution:
Phase: Untap
  → Check skip effects: Player has "Skip Untap"
  → Should skip? YES
  → Skip this phase entirely (don't untap permanents)

Phase: Upkeep
  → Check skip effects: No skip for upkeep
  → Should skip? NO
  → Execute normally
```

---

# PART 9: WIN/LOSS CONDITION OVERRIDES

## Scenario: "You Can't Lose The Game"

```python
# Card creates this effect:
cant_lose_effect = WinConditionEffect(
    name="Can't Lose",
    type="PreventLoss"
)

# During game, player takes lethal damage
damage_event = DamageEvent(player=player_a, amount=20)

# Step 1: Check for replacement effects
# Find all "damage" replacements
damage_replacements = player_a.get_replacements_for_event("damage")

# Step 2: Check for prevention effects
# (Can't Lose is technically a prevention)
# If player has "You can't lose", prevent the loss

# Step 3: After damage would make life 0 or negative
if player_a.life <= 0:
    loss_event = PlayerLossEvent(player=player_a, reason="life_0")
    
    # Check: Does player have effects preventing loss?
    prevention_effects = player_a.get_effects_of_type("PreventLoss")
    
    if prevention_effects:
        # Event is prevented
        loss_event = None
    
    if loss_event:
        # Player loses
        game_state.set_loser(player_a)
    else:
        # Player is still alive (can't lose prevents the loss)
        pass

# Result: Player takes 20 damage, life is 0 or negative,
#         but "You can't lose" prevents the loss event from triggering
```

---

# PART 10: IMPLEMENTATION SUMMARY

## The Right Architecture for MTG

```
1. PHASES ARE SEQUENCES (Definable, not hardcoded)
   └─ Can be skipped/reordered by effects

2. EFFECTS ARE HIERARCHICAL
   ├─ Static (continuous)
   ├─ Triggered (condition → stack)
   ├─ Replacement (replaces events, no stack)
   └─ Activated (cost + effect)

3. EFFECTS STACK & COMBINE
   └─ Replacement chains can be ordered by players

4. SERVICE REGISTRY FOR EXTENSIBILITY
   └─ New effects = new service, no engine changes

5. ORACLE TEXT → AUTOMATIC REGISTRATION
   └─ Cards declare effects, engine applies them

6. EVERYTHING CAN BE OVERRIDDEN
   └─ Skip steps, replace events, change win conditions
```

This architecture supports the MTG rules fully:
- ✅ RULE 500+ (Phases & Steps) - Definable sequences
- ✅ RULE 611 (Static Effects) - Continuous modifiers
- ✅ RULE 603 (Triggered) - Event-based effects
- ✅ RULE 614 (Replacement) - Event replacement chains
- ✅ RULE 602 (Activated) - Cost-based abilities
- ✅ RULE 616 (Ordering) - Player chooses replacement order

---

# CRITICAL IMPLEMENTATION REQUIREMENT FOR PHASE 2

When implementing the Rules Engine (Phase 2), MUST:

1. ✅ Define phases as executable sequences (not hardcoded)
2. ✅ Implement effect type hierarchy (Static/Triggered/Replacement/Activated)
3. ✅ Build effect registry/service pattern
4. ✅ Implement replacement effect chaining with ordering (RULE 616)
5. ✅ Parse oracle text → automatic effect registration
6. ✅ Allow effects to override game rules (skip phases, prevent loss, etc.)

Without these, will end up with hardcoded special cases for every card → unmaintainable.
