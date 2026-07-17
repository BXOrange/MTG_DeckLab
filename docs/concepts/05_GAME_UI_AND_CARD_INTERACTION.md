# MTG Deck Analyzer: Game UI & Card Interaction Model

---

# CORE PRINCIPLE: Cards Are Interactive Objects, Not Static Display

## The Problem with Traditional UI

```
Bad Approach:
┌──────────────────────────────────┐
│ Your Hand:                       │
│ • Island                         │
│ • Mountain                       │
│ • Lightning Bolt                 │
│ • Counterspell                   │
└──────────────────────────────────┘

Issue: How do I PLAY these cards? Just text names.
```

## The Solution: Card Objects with Actions

```
Good Approach:
┌──────────────────────────────────────────────────┐
│ Your Hand:                                       │
│ ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│ │ Island     │ │ Mountain   │ │ Lightning... │ │
│ │ Land       │ │ Land       │ │ Instant      │ │
│ │ Tap for U  │ │ Tap for R  │ │ Damage       │ │
│ │ [Play ▼]   │ │ [Play ▼]   │ │ [CAST ▼]     │ │
│ └────────────┘ └────────────┘ └──────────────┘ │
└──────────────────────────────────────────────────┘

Click on card → Show available actions
```

---

# PART 1: CARD DATA MODEL (Extended)

## Card with Action Methods

```python
class Card:
    # Identity
    id: str
    name: str
    mana_cost: dict[str, int]
    type_line: str
    oracle_text: str
    
    # What can I do with this card?
    can_cast: bool                   # Can this be played as spell?
    casting_cost: dict[str, int]     # Mana required
    casting_timing: str              # "instant", "sorcery", "land", etc.
    
    activated_abilities: list[ActivatedAbility] = []
    triggered_abilities: list[TriggeredAbility] = []
    
    # Properties
    is_land: bool
    is_creature: bool
    is_instant: bool
    is_sorcery: bool
    power: Optional[int]
    toughness: Optional[int]

class ActivatedAbility:
    """Ability that player can activate (has a cost)"""
    id: str                          # Unique within card
    name: str                         # e.g., "Tap for mana"
    cost: str                         # "{T}" or "{2}{U}" or other
    effect: str                       # "Add {U} to mana pool"
    targeting_required: bool
    targeting_type: str              # "single_creature", "player", etc.

class TriggeredAbility:
    """Ability that triggers automatically (no cost, just condition)"""
    id: str
    trigger_condition: str           # "when enters", "when casts", etc.
    effect: str
    targeting_required: bool
```

---

# PART 2: CARD ACTIONS (What Can Player Do?)

## Action Types per Card Type

### Land Card
```
Available Actions:
├─ PLAY_LAND (if main phase, haven't played land, land in hand)
│  └─ Effect: Add land to battlefield, put to graveyard next turn
└─ ACTIVATED_ABILITIES
   └─ TAP_FOR_MANA (if untapped, tapping cost met)
      └─ Effect: Add color to mana pool
```

### Instant Card
```
Available Actions:
├─ CAST_SPELL (any time player has priority)
│  ├─ Cost: Pay mana
│  ├─ Targeting: If spell has targets, select them
│  └─ Effect: Spell goes on stack, resolves based on text
└─ ACTIVATED_ABILITIES (if have any)
   └─ e.g., some instants have activated abilities
```

### Sorcery Card
```
Available Actions:
├─ CAST_SPELL (only during main phase, active player)
│  ├─ Cost: Pay mana
│  ├─ Targeting: If spell has targets, select them
│  └─ Effect: Spell goes on stack
└─ ACTIVATED_ABILITIES (if have any, rare)
```

### Creature Card
```
Available Actions:
├─ CAST_SPELL (like sorcery, during main phase)
│  ├─ Cost: Pay mana
│  ├─ Targeting: Some creatures have casting targets
│  └─ Effect: Spell goes on stack, resolves to battlefield
├─ ATTACK (during combat phase, if creature on battlefield)
│  └─ Effect: Declare as attacker
└─ ACTIVATED_ABILITIES
   └─ e.g., "{T}: Draw a card", "{2}{U}: Create token"
```

### Enchantment/Artifact Card
```
Available Actions:
├─ CAST_SPELL (like sorcery)
├─ ATTACK (if creature type AND first strike ability)
└─ ACTIVATED_ABILITIES
   └─ e.g., "{3}: Deal 1 damage"
```

---

# PART 3: SERVER-SIDE: Determine Available Actions

## On Each GameState Update, Server Sends Legal Actions

**Server Logic**:
```python
def get_legal_actions_for_player(game_state: GameState, player_id: str) -> list[Action]:
    """What can this player do RIGHT NOW?"""
    
    actions = []
    player = game_state.get_player(player_id)
    
    # 1. Can this player act? (Is it their turn? Do they have priority?)
    if not can_player_act(game_state, player_id):
        return [PassAction()]  # Only can pass
    
    # 2. What's the current phase?
    phase = game_state.current_phase
    
    # 3. For each card in hand, check what's legal
    for card in player.hand:
        
        # Can play land? (main phase, haven't played land yet, is land)
        if phase in ["main1", "main2"] and card.is_land:
            if not player.has_played_land_this_turn:
                actions.append(PlayLandAction(card))
        
        # Can cast as spell? (mana available, timing legal, no spells on stack)
        if can_cast_spell(card, game_state, player_id):
            cast_action = CastSpellAction(card)
            
            # If spell has targets, need to get valid targets
            if card.has_targets:
                valid_targets = get_valid_targets(card, game_state, player_id)
                cast_action.valid_targets = valid_targets
            
            actions.append(cast_action)
        
        # Can activate abilities? (has activated abilities, can pay cost)
        for ability in card.activated_abilities:
            if can_activate_ability(card, ability, game_state, player_id):
                actions.append(ActivateAbilityAction(card, ability))
    
    # 4. Always can pass
    actions.append(PassAction())
    
    return actions

def can_cast_spell(card: Card, game_state: GameState, player_id: str) -> bool:
    """Check RULE 601: Can this player cast this spell right now?"""
    player = game_state.get_player(player_id)
    
    # Must have priority
    if not game_state.player_has_priority(player_id):
        return False
    
    # Check timing (instant, sorcery, etc.)
    if card.is_instant:
        # RULE 601.3a: Can cast instant any time
        pass
    elif card.is_sorcery or card.is_creature:
        # RULE 601.2a: Can only cast during main phase
        if game_state.current_phase not in ["main1", "main2"]:
            return False
        # Active player only
        if not game_state.is_active_player(player_id):
            return False
        # No spells on stack (simplified: could be more complex)
        if len(game_state.stack) > 0:
            return False
    
    # Check mana cost
    if not can_pay_mana(card.mana_cost, player.mana_pool):
        return False
    
    return True

def can_activate_ability(card: Card, ability: ActivatedAbility, game_state: GameState, player_id: str) -> bool:
    """Check RULE 602: Can player activate this ability?"""
    player = game_state.get_player(player_id)
    
    # Must have priority (unless it's a mana ability, special case)
    if not is_mana_ability(ability):
        if not game_state.player_has_priority(player_id):
            return False
    
    # Must be able to pay cost
    if not can_pay_ability_cost(ability.cost, player, card, game_state):
        return False
    
    # Card must be on battlefield (activated abilities are for permanents)
    if card not in player.battlefield:
        return False
    
    return True
```

**Server Sends to Client**:
```json
{
  "type": "game_state_update",
  "legal_actions": [
    {
      "id": "action_1",
      "type": "play_land",
      "card_id": "card_island",
      "card_name": "Island",
      "description": "Play Island"
    },
    {
      "id": "action_2",
      "type": "cast_spell",
      "card_id": "card_lightning_bolt",
      "card_name": "Lightning Bolt",
      "description": "Cast Lightning Bolt",
      "targeting_required": true,
      "valid_targets": ["player_2", "creature_1", "creature_2"],
      "mana_cost": {"red": 1}
    },
    {
      "id": "action_3",
      "type": "activate_ability",
      "card_id": "card_goblin_electromancer",
      "card_name": "Goblin Electromancer",
      "ability_name": "Shock ability",
      "description": "{2}{R}: This creature deals 1 damage to target creature",
      "targeting_required": true,
      "valid_targets": ["creature_1", "creature_2", "creature_3"]
    },
    {
      "id": "action_4",
      "type": "pass",
      "description": "Pass priority"
    }
  ]
}
```

---

# PART 4: CLIENT-SIDE: Hand UI & Interaction

## Hand Display Component

```
┌─────────────────────────────────────────────────────────────┐
│ YOUR HAND (7 cards)                                          │
│                                                              │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│ │  Island  │ │Mountain  │ │Lightning │ │Counter-  │ ...   │
│ │          │ │          │ │  Bolt    │ │  spell   │       │
│ │   Land   │ │   Land   │ │ Instant  │ │ Instant  │       │
│ │          │ │          │ │          │ │          │       │
│ │ Tap:⊗ U │ │ Tap:⊗ R │ │ Cost:⊗ R │ │Cost:⊗ UU │       │
│ │   [▼]    │ │   [▼]    │ │  [▼]     │ │  [▼]     │       │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│     ↑             ↑             ↑            ↑              │
│   Click         Click         Click        Click           │
│   to see        to see        to see       to see          │
│  options       options       options      options          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Card Component (React Example)

```jsx
// CardInHand.jsx
export const CardInHand = ({ card, legalActions, onCardClick }) => {
  const [showMenu, setShowMenu] = useState(false);
  
  // Find all actions this card can do
  const cardActions = legalActions.filter(
    action => action.card_id === card.id
  );
  
  const handleCardClick = () => {
    if (cardActions.length === 0) {
      // No valid actions for this card
      alert(`${card.name}: No legal actions`);
      return;
    }
    
    if (cardActions.length === 1) {
      // Only one action? Execute it immediately (e.g., pass)
      onActionSelected(cardActions[0]);
    } else {
      // Multiple actions? Show menu
      setShowMenu(!showMenu);
    }
  };
  
  const handleActionClick = (action) => {
    if (action.targeting_required) {
      // Need to select target first
      onTargetingStarted(action);
    } else {
      // No targeting, execute immediately
      onActionSelected(action);
    }
    setShowMenu(false);
  };
  
  return (
    <div className="card-in-hand">
      <div
        className={`card-display ${cardActions.length > 0 ? 'clickable' : 'disabled'}`}
        onClick={handleCardClick}
      >
        <div className="card-name">{card.name}</div>
        <div className="card-type">{card.type_line}</div>
        <div className="card-cost">
          {card.is_land ? `Tap: ${card.mana_produces}` : `Cost: ${formatManaCost(card.mana_cost)}`}
        </div>
        <div className="card-text">{card.oracle_text}</div>
        <div className="card-stats">
          {card.power ? `${card.power}/${card.toughness}` : ''}
        </div>
      </div>
      
      {/* Action Menu */}
      {showMenu && (
        <div className="action-menu">
          {cardActions.map(action => (
            <div
              key={action.id}
              className="action-option"
              onClick={() => handleActionClick(action)}
            >
              <div className="action-name">
                {getActionLabel(action)}
              </div>
              <div className="action-desc">
                {action.description}
              </div>
              {action.targeting_required && (
                <div className="action-hint">
                  (Select target)
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

function getActionLabel(action) {
  switch (action.type) {
    case 'play_land': return '🌲 Play Land';
    case 'cast_spell': return '✨ Cast Spell';
    case 'activate_ability': return '⚙️ Activate Ability';
    default: return action.type;
  }
}

function formatManaCost(cost) {
  // Convert {W: 1, U: 1, B: 0, R: 1, G: 0, C: 2}
  // to "1WUR2" or similar
  const colors = ['W', 'U', 'B', 'R', 'G'];
  let result = '';
  if (cost.generic) result += cost.generic;
  colors.forEach(c => {
    for (let i = 0; i < (cost[c] || 0); i++) {
      result += c;
    }
  });
  return result || '0';
}
```

## Hand Layout Considerations

### Dense View (Show all cards at once)
```
Pros: See entire hand, quick scanning
Cons: Cards small, details hard to read

Width per card: ~80px
Show: Name, Type, Mana Cost
Action menu: Hover or click shows full card + actions
```

### Expanded View (Show one card at a time)
```
Pros: Large cards, clear details, easy to read
Cons: Can't see full hand at once

Default: Show first card large
Controls: Left/Right to browse
Hover tooltip: Show other card names for quick ref
```

### Recommended: Hybrid
```
┌──────────────────────────────────────────────────────────┐
│ LEFT: Dense hand view (7 small cards)                    │
│ RIGHT: Expanded card view (selected card)                │
│                                                           │
│ ┌─────────────────┐    ┌────────────────────────────┐   │
│ │ I │ M │ L │ C │ L   │ Lightning Bolt              │   │
│ │ S │ N │ B │ S │ S   │                            │   │
│ │ L │ T │ O │ P │ P   │ Instant                    │   │
│ │ A │ L │ L │ L │ L   │                            │   │
│ │   │   │   │   │     │ Cost: 1R                   │   │
│ │ 1 │ 2 │ 3 │ 4 │ 5   │                            │   │
│ └─────────────────┘    │ Deal 3 damage to target    │   │
│                         │ creature or player        │   │
│                         │                            │   │
│                         │ [CAST ▼]                   │   │
│                         │                            │   │
│                         │ ├─ Cast (red target)      │   │
│                         │ ├─ Cast (player 2)        │   │
│                         │ └─ Examine details        │   │
│                         └────────────────────────────┘   │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

---

# PART 5: TARGETING SYSTEM

## Targeting Flow

```
User clicks card → Card menu → User clicks "Cast Spell"
  ↓
Targeting Required? (From legal_actions.targeting_required)
  ├─ NO: Send action to server immediately
  └─ YES: Enter targeting mode
```

## Targeting UI

```
┌────────────────────────────────────────────────────┐
│ TARGETING MODE: Select target for Lightning Bolt   │
│                                                    │
│ Opponent's Board:                                  │
│ ┌──────────────┐ ┌──────────────┐                │
│ │ Creature A   │ │ Creature B   │                │
│ │ (3/3)        │ │ (2/2)        │                │
│ │ [SELECT ▼]   │ │ [SELECT ▼]   │                │
│ └──────────────┘ └──────────────┘                │
│                                                    │
│ Or:                                                │
│ ┌──────────────────────────────────────────────┐ │
│ │ Opponent Player (20 life)                    │ │
│ │ [SELECT PLAYER AS TARGET]                    │ │
│ └──────────────────────────────────────────────┘ │
│                                                    │
│ Valid targets: 4 options                          │
│ [Cancel]                                          │
└────────────────────────────────────────────────────┘
```

## Targeting Component (React)

```jsx
export const TargetingPanel = ({ action, validTargets, onTargetSelected, onCancel }) => {
  const [selectedTarget, setSelectedTarget] = useState(null);
  
  const handleTargetClick = (target) => {
    setSelectedTarget(target);
    // Highlight the target
  };
  
  const handleConfirm = () => {
    if (!selectedTarget) {
      alert('Please select a target');
      return;
    }
    onTargetSelected(action, selectedTarget);
  };
  
  return (
    <div className="targeting-panel">
      <div className="targeting-prompt">
        {action.description}: Select target
      </div>
      
      <div className="targets-grid">
        {validTargets.map(target => (
          <div
            key={target.id}
            className={`target ${selectedTarget?.id === target.id ? 'selected' : ''}`}
            onClick={() => handleTargetClick(target)}
          >
            <div className="target-name">{target.name}</div>
            <div className="target-info">
              {target.type === 'creature' && `${target.power}/${target.toughness}`}
              {target.type === 'player' && `${target.life} life`}
            </div>
            <div className="target-checkmark">
              {selectedTarget?.id === target.id && '✓'}
            </div>
          </div>
        ))}
      </div>
      
      <div className="targeting-buttons">
        <button onClick={handleCancel}>Cancel</button>
        <button onClick={handleConfirm} disabled={!selectedTarget}>
          Confirm Target
        </button>
      </div>
    </div>
  );
};
```

---

# PART 6: ABILITY ACTIVATION

## Activated Abilities on Permanents

### During Game: Creature on Battlefield

```
┌────────────────────────────────────────┐
│ GOBLIN ELECTROMANCER                   │
│ (2/2 Creature, untapped)               │
│                                         │
│ Text:                                   │
│ "Whenever you cast an instant or       │
│  sorcery spell, Goblin Electromancer   │
│  gets +1/+2 until end of turn."        │
│                                         │
│ Activated Ability:                      │
│ "{T}: Deal 1 damage to target          │
│  creature or player"                   │
│                                         │
│ [ABILITIES ▼]                          │
│ ├─ {T}: Deal 1 damage                  │
│ └─ (No other activated abilities)      │
│                                         │
│ [TAP/UNTAP]                            │
└────────────────────────────────────────┘
```

### Activated Ability Flow

```
User clicks creature → Shows options → User clicks "{T}: Deal 1 damage"
  ↓
Targeting required? YES → Show targeting UI
  ↓
User selects target → Confirm
  ↓
Send to server: {
  type: "activate_ability",
  card_id: "goblin_electromancer",
  ability_id: "shock_ability",
  target: "player_2"
}
```

---

# PART 7: GAME ACTIONS PANEL (Non-Hand Actions)

## Actions Available Outside of Hand

```
┌──────────────────────────────────┐
│ GAME ACTIONS                     │
│                                  │
│ Phase: Main Phase I              │
│ Priority: You (Player 1)         │
│ Mana Available: ⊗U ⊗R ⊗2         │
│                                  │
│ ┌────────────────────────────┐  │
│ │ [Play Land]                │  │
│ │ Play a land from hand      │  │
│ └────────────────────────────┘  │
│                                  │
│ ┌────────────────────────────┐  │
│ │ [PASS PRIORITY]            │  │
│ │ End your priority window   │  │
│ └────────────────────────────┘  │
│                                  │
│ [MULLIGAN] (only at game start)  │
│                                  │
└──────────────────────────────────┘
```

---

# PART 8: COMPLETE CARD INTERACTION FLOW

## End-to-End Example: Cast Lightning Bolt

```
STEP 1: Display Legal Actions
Server → Client:
{
  "legal_actions": [
    {
      "id": "cast_lightning",
      "type": "cast_spell",
      "card_id": "card_lightning_bolt",
      "description": "Cast Lightning Bolt",
      "targeting_required": true,
      "valid_targets": ["player_2", "creature_opponent_1"]
    },
    { "id": "pass_action", "type": "pass", "description": "Pass" }
  ]
}

Client displays Lightning Bolt card with:
  - Card image/name
  - Mana cost: 1R
  - Type: Instant
  - Text: "Deal 3 damage..."
  - Action button: "[CAST ▼]"

STEP 2: Player Clicks Card
Player clicks Lightning Bolt card
Client shows action menu:
  ├─ ✨ Cast Spell (requires target)
  └─ 📋 View Details

STEP 3: Player Selects Action
Player clicks "✨ Cast Spell"
Client knows targeting_required = true
Enters targeting mode

STEP 4: Player Selects Target
Targeting panel shows:
  ├─ [Player 2] (20 life)
  └─ [Creature: Grizzly Bear] (2/2)

Player clicks "Player 2"
Client highlights selection
Player clicks "Confirm"

STEP 5: Send Action to Server
Client → Server:
{
  "type": "player_action",
  "action": {
    "id": "cast_lightning",
    "type": "cast_spell",
    "card_id": "card_lightning_bolt",
    "target": "player_2"
  }
}

STEP 6: Server Validates & Executes
Server:
  ✓ Can cast Lightning Bolt right now? YES
  ✓ Can pay 1R mana? YES
  ✓ Is target valid? YES (player)
  Execute: Deal 3 damage to Player 2

STEP 7: Update Game State
Server broadcasts:
{
  "type": "game_state_update",
  "message": "Player 1 cast Lightning Bolt, dealing 3 damage to Player 2",
  "game_state": {
    "player_1": { ... },
    "player_2": {
      "life": 17,  # Changed from 20
      ...
    },
    ...
  },
  "legal_actions": [
    { "type": "pass", "description": "Pass" },
    ...
  ]
}

STEP 8: Update Client Display
Both clients receive update:
  ✓ Lightning Bolt disappears from Player 1's hand
  ✓ Player 2's life: 20 → 17
  ✓ Game log: "Player 1 cast Lightning Bolt..."
  ✓ Update legal actions for next priority holder
```

---

# PART 9: KEYBOARD SHORTCUTS (Optional)

```
1-9: Select card 1-9 in hand
C: Cast selected card
A: Activate ability on selected card
T: Attack with selected creature
B: Block with selected creature
ESC: Cancel targeting / close menu
SPACE: Pass priority
U: Undo (if allowed)
```

---

# PART 10: ACCESSIBILITY FEATURES

```
For screen readers / keyboard-only players:

1. All cards have alt-text with full card details
2. Tab navigation through hand → legal actions
3. Enter to select action
4. Arrow keys to select targets
5. Color-not-required for targeting (symbols + text)
6. Large font options
7. High contrast mode
```

---

# CONCLUSION

**Key Principles**:
1. ✅ Each card is interactive (not static text)
2. ✅ Legal actions determined server-side, displayed client-side
3. ✅ Clicking card → menu of available actions
4. ✅ Action → targeting UI (if required) → execute
5. ✅ All validation server-side (client just displays)
6. ✅ Clean, responsive UI (not cluttered)

**This enables UC3 & UC4**: Goldfisch & Multiplayer both depend on being able to play cards easily.
