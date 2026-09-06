# DeckLab: Server-Client Web Architecture

---

# STRATEGIC SHIFT: From Monolith to Distributed System

## Before (CLI Monolith)
```
[Local CLI]
  ├─ Card DB
  ├─ Parser
  ├─ Game Engine
  ├─ Rules
  ├─ UI
  └─ Analysis

Problem: Single machine, single user, hard to scale
```

## After (Server-Client Web)
```
[Web Browser Client - HTML5]        [Server]
  ├─ Game UI Display                ├─ Card DB
  ├─ User Input                     ├─ Parser & Validator
  ├─ Game State Display             ├─ Game Engine (Turn Loop, Rules)
  └─ Network Layer                  ├─ Game Session Manager
       ↕ (WebSocket)                ├─ Matchmaking
       ↕                            ├─ LLM Integration
       ↕                            ├─ Persistence (Decks, Users, Games)
                                    ├─ Bot AI
                                    └─ Analysis Engine
```

**Benefits**:
- ✅ Multi-player (people from different machines)
- ✅ Web-based UI (responsive, modern)
- ✅ Server-side game logic (no cheating possible)
- ✅ Scalable (multiple clients → one server)
- ✅ Persistent storage (save games, decks, stats)
- ✅ Matchmaking service (find opponents)
- ✅ Analysis centralized (expensive computation on server)

---

# PART 1: SYSTEM ARCHITECTURE OVERVIEW

## High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ PLAYER 1 BROWSER                   PLAYER 2 BROWSER             │
│ ┌────────────────────┐             ┌────────────────────┐       │
│ │ HTML5 Web Client   │             │ HTML5 Web Client   │       │
│ │ ├─ React/Vue/etc   │             │ ├─ React/Vue/etc   │       │
│ │ ├─ Game UI Display │             │ ├─ Game UI Display │       │
│ │ ├─ Input Handler   │             │ ├─ Input Handler   │       │
│ │ └─ Network Layer   │             │ └─ Network Layer   │       │
│ └────────────┬───────┘             └────────────┬───────┘       │
│              │                                   │               │
│              └───────────────┬────────────────────┘               │
│                              │ WebSocket/REST                    │
└──────────────────────────────┼─────────────────────────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │  BACKEND SERVER          │
                  │                          │
                  │  ┌──────────────────┐   │
                  │  │ Game Manager     │   │
                  │  │ ├─ Sessions      │   │
                  │  │ ├─ Turn Manager  │   │
                  │  │ └─ Game Loop     │   │
                  │  └──────────────────┘   │
                  │                          │
                  │  ┌──────────────────┐   │
                  │  │ Rules Engine     │   │
                  │  │ ├─ Casting       │   │
                  │  │ ├─ Stack         │   │
                  │  │ └─ Mana System   │   │
                  │  └──────────────────┘   │
                  │                          │
                  │  ┌──────────────────┐   │
                  │  │ Persistence      │   │
                  │  │ ├─ Deck DB       │   │
                  │  │ ├─ User DB       │   │
                  │  │ └─ Game History  │   │
                  │  └──────────────────┘   │
                  │                          │
                  │  ┌──────────────────┐   │
                  │  │ Services         │   │
                  │  │ ├─ Matchmaking   │   │
                  │  │ ├─ Analysis      │   │
                  │  │ ├─ Bot AI        │   │
                  │  │ └─ LLM Integration  │
                  │  └──────────────────┘   │
                  │                          │
                  └──────────────────────────┘
                        │
                  ┌─────▼──────────┐
                  │ External Data  │
                  │ ├─ Scryfall API│
                  │ └─ LLM API     │
                  └────────────────┘
```

---

# PART 2: SERVER-SIDE ARCHITECTURE

## Server Components (Layers)

```
┌─────────────────────────────────────────────────────────────┐
│ ORCHESTRATION LAYER                                          │
│ ├─ WebSocket Message Router                                 │
│ ├─ HTTP REST API Router                                     │
│ ├─ Session Manager (which player, which game?)              │
│ └─ Event Broadcaster (send to all clients in game)          │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ GAME LOGIC LAYER (Rules-Driven)                             │
│ ├─ Game Manager (lifecycle: create, play, end)              │
│ ├─ Turn Manager (turn progression)                          │
│ ├─ Rules Engine (RULE 601/608/504/117/603/607)             │
│ ├─ Action Processor (cast spell, attack, etc.)              │
│ └─ Event System (triggered abilities, etc.)                │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ SERVICE LAYER                                                │
│ ├─ Matchmaking Service (find opponent)                       │
│ ├─ Bot Service (automated players)                           │
│ ├─ Analysis Service (LLM, deck analysis)                     │
│ ├─ Persistence Service (save/load)                           │
│ └─ Notification Service (game updates)                       │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ DATA LAYER                                                   │
│ ├─ Card Repository (card data)                              │
│ ├─ Deck Repository (save decks)                              │
│ ├─ User Repository (users, accounts)                         │
│ ├─ Game Repository (game history)                            │
│ └─ Session Repository (active games)                         │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│ DATABASE (PostgreSQL or similar)                             │
│ ├─ Cards table (name, mana_cost, type, etc.)               │
│ ├─ Decks table (user_id, commander, cards)                  │
│ ├─ Users table (username, password_hash, etc.)              │
│ ├─ Games table (game_history, result, players)              │
│ ├─ Sessions table (active_games, state)                     │
│ └─ Matches table (pending games, matchmaking queue)         │
└─────────────────────────────────────────────────────────────┘
```

## Server Responsibilities

### S1: Authentication & Session Management
```
When user connects:
1. Browser sends auth token (or login)
2. Server validates token
3. Server creates/resumes session
4. Server tracks user connection (IP, browser, session_id)
5. Server can later:
   - Reconnect if browser refreshes
   - Kick if inactive too long
   - Support multiple tabs (careful!)
```

### S2: Game Session Management
```
When game starts:
1. Server creates GameSession object
2. Stores: Player1, Player2, GameState, Turn, Phase, Priority
3. Stores: All actions taken (game log)
4. Sends initial state to both clients
5. Listens for actions from each client
6. Validates actions server-side
7. Updates game state
8. Broadcasts updates to both clients
9. When game ends: saves to database, sends result
```

### S3: Action Processing Pipeline
```
Client sends action: "CastSpell Lightning Bolt targeting Player 2"

Server-side:
1. Validate: Is this player's turn?
2. Validate: Is action legal (mana cost, timing, etc.)?
3. Execute: Call RulesEngine.CastSpell()
4. Update: GameState
5. Trigger: Any triggered abilities?
6. Broadcast: "Player1 cast Lightning Bolt, dealing 3 damage to Player2"
7. Send: Updated GameState to both clients
8. Next: Game loop (check whose priority, etc.)
```

### S4: Persistence
```
Before Game Starts:
- Load Player1's deck from database
- Load Player2's deck from database

During Game:
- Optional: Save game state every N actions (for resume)

After Game:
- Save final game state
- Save winner/loser/result
- Update player statistics (win/loss count)
- Allow replay of game
```

### S5: Matchmaking
```
Player clicks "Find Opponent":
1. Join matchmaking queue
2. Server waits for another player
3. When 2nd player joins:
   - Remove both from queue
   - Create game session
   - Load both decks
   - Start game
   - Send "game ready" to both clients
```

---

# PART 3: CLIENT-SIDE ARCHITECTURE

## Client Components

```
┌──────────────────────────────────────────────────────────┐
│ HTML5 WEB CLIENT (Browser)                               │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ PRESENTATION LAYER (React/Vue Components)          │  │
│ │ ├─ Game Board Display                              │  │
│ │ │  ├─ Player Info (life, hand size, library)      │  │
│ │ │  ├─ Battlefield (creatures, permanents)         │  │
│ │ │  ├─ Stack Display                               │  │
│ │ │  └─ Graveyard/Exile View                        │  │
│ │ ├─ Action Panel                                    │  │
│ │ │  ├─ List of legal actions                       │  │
│ │ │  ├─ Spell casting interface                     │  │
│ │ │  ├─ Attack/Block interface                      │  │
│ │ │  └─ Pass button                                 │  │
│ │ └─ Game Chat/Log                                   │  │
│ │    ├─ Recent actions ("P1 cast Lightning Bolt")   │  │
│ │    └─ Player chat (optional)                       │  │
│ └────────────────────────────────────────────────────┘  │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ STATE MANAGEMENT (Redux or Vuex)                   │  │
│ │ ├─ myPlayer state (hand, life, mana pool)         │  │
│ │ ├─ opponentPlayer state (partial, not hand!)      │  │
│ │ ├─ GameState (phase, turn, stack, etc.)           │  │
│ │ ├─ UI state (what can I do now?)                  │  │
│ │ └─ Connection state (connected? latency?)         │  │
│ └────────────────────────────────────────────────────┘  │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ INPUT HANDLER                                       │  │
│ │ ├─ Parse clicks/form submissions                   │  │
│ │ ├─ Build action objects                            │  │
│ │ ├─ Validate input locally (optional early check)  │  │
│ │ └─ Send to server via WebSocket                    │  │
│ └────────────────────────────────────────────────────┘  │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ NETWORK LAYER (WebSocket + REST)                   │  │
│ │ ├─ WebSocket connection to /ws/game/{game_id}     │  │
│ │ ├─ Receive: GameState updates                      │  │
│ │ ├─ Send: Player actions                            │  │
│ │ ├─ Receive: Error messages                         │  │
│ │ ├─ REST calls for: Auth, Deck management, etc.    │  │
│ │ └─ Handle disconnection/reconnection               │  │
│ └────────────────────────────────────────────────────┘  │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

## Client Responsibilities

### C1: Presentation Only
- Display GameState (never calculate it)
- Show what actions are legal (based on server state)
- Render UI updates in real-time
- **NO Game Logic**: Client cannot decide if spell is legal
- **NO Cheating**: All validation happens server-side

### C2: User Input
- Capture clicks/form submissions
- Build action messages (structured JSON)
- Send to server
- Wait for response
- Do NOT execute action locally (wait for server confirmation)

### C3: State Synchronization
- Client maintains local copy of GameState
- Server is authoritative source
- When server sends update: update local state
- When local action fires: wait for server echo (or error)
- If disconnected: ask server for current state

### C4: Responsive UI
- While waiting for server: show "Thinking..." or spinner
- If action fails: show error message
- If latency > 1s: show latency indicator
- Support reconnection if disconnected

---

# PART 4: COMMUNICATION PROTOCOL (API)

## WebSocket Messages (Real-time Game Updates)

### Client → Server (Player Action)

```json
{
  "type": "player_action",
  "game_id": "game_12345",
  "player_id": "player_1",
  "action": {
    "type": "cast_spell",
    "card_id": "card_lightning_bolt",
    "targets": ["player_2"]
  }
}
```

### Server → Client (Game State Update)

```json
{
  "type": "game_state_update",
  "timestamp": "2026-07-01T10:30:45Z",
  "turn": 1,
  "active_player": "player_1",
  "phase": "main1",
  "game_state": {
    "player_1": {
      "id": "player_1",
      "life": 20,
      "hand": ["Island", "Mountain", "Lightning Bolt"],
      "library_size": 97,
      "graveyard": [],
      "battlefield": ["Island", "Mountain"],
      "mana_pool": {"blue": 1, "red": 1}
    },
    "player_2": {
      "id": "player_2",
      "life": 20,
      "hand_size": 7,
      "library_size": 100,
      "graveyard": [],
      "battlefield": []
    },
    "stack": [],
    "game_log": [
      "Turn 1: Player 1 plays Island",
      "Turn 1: Player 1 plays Mountain"
    ]
  },
  "legal_actions": [
    {
      "type": "cast_spell",
      "card_id": "card_lightning_bolt",
      "valid_targets": ["player_2"]
    },
    {
      "type": "pass"
    }
  ]
}
```

### Server → Client (Action Result)

```json
{
  "type": "action_result",
  "success": true,
  "action": "cast_spell",
  "message": "Player 1 cast Lightning Bolt",
  "game_state_update": { ... }
}
```

Or if failed:

```json
{
  "type": "action_result",
  "success": false,
  "action": "cast_spell",
  "error": "Insufficient mana: need 1 Red, have 0 Red"
}
```

## REST API Endpoints (Non-game)

```
POST /api/auth/login
  Input: username, password
  Output: auth_token

POST /api/auth/signup
  Input: username, password, email
  Output: auth_token

POST /api/decks
  Input: deck_list, commander_id
  Output: deck_id
  
GET /api/decks/{deck_id}
  Output: deck object

POST /api/decks/{deck_id}/analyze
  Input: (none, uses deck)
  Output: deck analysis (calls LLM)

GET /api/cards/search
  Input: query
  Output: matching cards

POST /api/games/matchmake
  Input: deck_id
  Output: game_id (when opponent found)

POST /api/games/{game_id}/actions
  Input: action object
  Output: result

WebSocket /ws/game/{game_id}
  Bi-directional: Player actions ↔ Game updates
```

---

# PART 5: DATA FLOW EXAMPLES

## Example 1: Cast a Spell

```
PLAYER 1 (Browser)
  ├─ Sees "Lightning Bolt" in hand
  ├─ Clicks it
  ├─ Selects target: "Player 2"
  ├─ Clicks "Cast"
  └─ Sends WebSocket message:
     {
       "type": "player_action",
       "action": {
         "type": "cast_spell",
         "card_id": "lightning_bolt",
         "targets": ["player_2"]
       }
     }
       ↓
SERVER
  ├─ Validates: Is it Player 1's turn?
  ├─ Validates: Does Player 1 have priority?
  ├─ Validates: Can Player 1 pay mana cost?
  ├─ Executes: RulesEngine.CastSpell(spell, target)
  ├─ Updates: GameState
  ├─ Checks: Are there triggered abilities?
  ├─ Creates: Event ("spell_cast")
  ├─ Resolves: Any immediate triggers
  └─ Broadcasts WebSocket to BOTH players:
     {
       "type": "game_state_update",
       "message": "Player 1 cast Lightning Bolt, dealing 3 damage",
       "game_state": { ... updated state ... }
     }
       ↓
BOTH CLIENTS
  ├─ Receive update
  ├─ Update local GameState
  ├─ Update UI
  │  ├─ Remove Lightning Bolt from hand
  │  ├─ Show Lightning Bolt on stack (briefly)
  │  ├─ Resolve stack (show damage)
  │  └─ Update Player 2 life (20 → 17)
  └─ Update legal actions
```

## Example 2: Multiplayer Simultaneous Triggers

```
SERVER
  ├─ Spell resolves
  ├─ Event: "creature_enters_battlefield"
  ├─ Finds: Both players have triggered abilities
  │  - Player 1: Goblin Electromancer (+1/+2)
  │  - Player 2: Faerie Guard (draw a card)
  ├─ Applies: RULE 607.1 (Active player orders)
  ├─ Sends to BOTH clients:
     {
       "type": "triggers_pending",
       "active_player": "player_1",
       "triggers": [
         { "source": "goblin_electromancer", "effect": "+1/+2" },
         { "source": "faerie_guard", "effect": "draw" }
       ],
       "message": "Player 1: order your triggers"
     }
       ↓
PLAYER 1 (Browser)
  ├─ Sees prompt: "Order your triggers"
  ├─ Sees list: [Goblin, Faerie Guard]
  ├─ Drags to order them
  ├─ Clicks "Continue"
  └─ Sends:
     {
       "type": "player_action",
       "action": {
         "type": "order_triggers",
         "order": ["goblin_electromancer", "faerie_guard"]
       }
     }
       ↓
SERVER
  ├─ Resolves triggers in order
  ├─ Updates: GameState
  └─ Broadcasts: Updated state to both clients
```

---

# PART 6: DEPLOYMENT MODEL

## Local Development

```
Backend (Python):
  python -m mtg_server --port 5000

Frontend (Node.js):
  npm start → webpack dev server :3000
  Browser: http://localhost:3000

Both running locally
```

## Production Deployment

```
Architecture:
┌──────────────────┐
│ Nginx/Reverse    │
│ Proxy            │
├──────────────────┤
│ Backend Server   │ (Python Flask/FastAPI)
│ (Docker)         │ 1+ instances for load balancing
├──────────────────┤
│ PostgreSQL DB    │ Cloud managed or self-hosted
├──────────────────┤
│ Redis (optional) │ For session caching, pub/sub
└──────────────────┘

Clients:
┌──────────────────┐
│ CDN              │ HTML/CSS/JS static files
│ (CloudFront)     │
└──────────────────┘
```

## Scaling Considerations

**Horizontal Scaling**:
- Multiple backend servers behind load balancer
- Sessions use Redis/memcached for shared state
- Each game session "sticks" to one server (sticky sessions)

**WebSocket Scaling**:
- Use Redis pub/sub for broadcasting updates
- Each server receives: needs to forward to connected clients

**Database Scaling**:
- Read replicas for queries
- Master for writes
- Indexed heavily (game lookups, user lookups)

---

# PART 7: REVISED 7-PHASE BUILD PLAN

## PHASE 1: Data Layer + API Foundation (Weeks 1-2)

**Server-Side (Weeks 1-2)**:
- [ ] Database schema (Card, Deck, User, Game, Session, Match tables)
- [ ] Card DB + Scryfall integration
- [ ] Deckliste Parser
- [ ] Validator (Commander rules)
- [ ] Flask/FastAPI server setup
- [ ] Basic REST API endpoints (/api/cards, /api/decks)
- [ ] User authentication (login/signup)
- [ ] Session management

**Client-Side (Weeks 1-2)**:
- [ ] React/Vue project setup
- [ ] Basic layout (navbar, sidebar, main area)
- [ ] Login page
- [ ] Deck builder page (list decks)
- [ ] Cards display (search cards)
- [ ] HTTP client setup (fetch, axios)

### Deliverables:
- ✅ Backend server with database
- ✅ REST API for auth, decks, cards
- ✅ Frontend with login and deck management
- ✅ Can create/load decks

---

## PHASE 2: Core Rules Engine (Weeks 3-4)

**Server-Side (Weeks 3-4)**:
- [ ] All rules implementation (same as before)
  - RULE 601 (Casting)
  - RULE 608 (Stack)
  - RULE 504 (Mana)
  - RULE 117 (Priority)
  - RULE 603/607 (Triggered Abilities)
  - Combat, State-Based Actions
- [ ] GameSession class (in-memory game state)
- [ ] Action processing pipeline
- [ ] WebSocket server setup (/ws/game/{game_id})

**Client-Side (Weeks 3-4)**:
- [ ] No changes (not used yet)

### Deliverables:
- ✅ Working rules engine (server-side)
- ✅ WebSocket server ready
- ✅ Can process game actions

---

## PHASE 3: Game Loop & WebSocket Integration (Weeks 5-6)

**Server-Side (Weeks 5-6)**:
- [ ] Game loop (turn progression)
- [ ] Turn manager
- [ ] Phase manager
- [ ] Action validator
- [ ] State broadcasts (send GameState to clients)
- [ ] Connect WebSocket to game loop
- [ ] Handle disconnects/reconnects

**Client-Side (Weeks 5-6)**:
- [ ] Game display component (battlefields, hands, stack)
- [ ] State management (Redux/Vuex)
- [ ] WebSocket client setup
- [ ] Connect to server, receive GameState updates
- [ ] Display state (read-only for now)
- [ ] Mulligan interface

### Deliverables:
- ✅ Server can run full game (automated)
- ✅ Client can view game state in real-time
- ✅ WebSocket communication works

---

## PHASE 4: Player Input & Goldfisch Mode (Weeks 7-8)

**Server-Side (Weeks 7-8)**:
- [ ] Accept player actions via WebSocket
- [ ] Validate actions
- [ ] Update GameState
- [ ] Broadcast results
- [ ] Handle: cast spell, attack, block, pass, mulligan

**Client-Side (Weeks 7-8)**:
- [ ] Action panel (show legal actions)
- [ ] Input handlers (buttons, forms for actions)
- [ ] Send actions to server
- [ ] Handle action results (success/error)
- [ ] Show error messages
- [ ] Game log display (action history)
- [ ] Mulligan UI

### Deliverables:
- ✅ Can play goldfisch (1 player vs. nothing)
- ✅ Full UI for playing
- ✅ Error handling

---

## PHASE 5: Multiplayer & Matchmaking (Weeks 9-10)

**Server-Side (Weeks 9-10)**:
- [ ] Matchmaking service
  - [ ] Matchmaking queue (Redis or DB)
  - [ ] Find opponent
  - [ ] Create game session with 2 players
- [ ] Priority system for 2 players
- [ ] Turn switching (Player 1 turn → Player 2 turn)
- [ ] Opponent info tracking (don't reveal hand)
- [ ] Game result tracking (winner/loser)
- [ ] Persistence (save completed games)

**Client-Side (Weeks 9-10)**:
- [ ] Matchmaking UI
  - [ ] "Find Opponent" button
  - [ ] Waiting screen ("Searching...")
  - [ ] "Cancel search" button
- [ ] Opponent info display (life, permanents, hand size)
- [ ] "Your turn" vs. "Opponent's turn" indicator
- [ ] Show: whose priority is it?
- [ ] Timeout handling (auto-pass if opponent takes too long)

### Deliverables:
- ✅ 2-player matchmaking works
- ✅ Can play full 2-player game
- ✅ Proper turn/priority management
- ✅ Games saved to database

---

## PHASE 6: LLM Deck Analysis (Weeks 11-12)

**Server-Side (Weeks 11-12)**:
- [ ] LLM integration (Claude API)
- [ ] Deck formatter
- [ ] Prompt templates
- [ ] Output parser
- [ ] Analysis caching
- [ ] REST endpoint: POST /api/decks/{deck_id}/analyze

**Client-Side (Weeks 11-12)**:
- [ ] Analyze button on deck view
- [ ] Loading spinner during analysis
- [ ] Analysis results display
  - [ ] Win conditions
  - [ ] Archetype
  - [ ] Synergies
  - [ ] Issues
  - [ ] Scores
- [ ] Cache display ("Analysis from X ago")

### Deliverables:
- ✅ Can analyze any deck via LLM
- ✅ Results displayed nicely
- ✅ Caching works

---

## PHASE 7: Bot Automation (Weeks 13-14)

**Server-Side (Weeks 13-14)**:
- [ ] Bot service (AI player)
- [ ] Action evaluator
- [ ] Strategy engine
- [ ] Decision maker
- [ ] Can take turns automatically
- [ ] Game modes:
  - [ ] Bot vs. Bot
  - [ ] Human vs. Bot (selectable)

**Client-Side (Weeks 13-14)**:
- [ ] Game creation: pick opponent type (Human / Bot)
- [ ] Bot speed control (fast / slow for readability)
- [ ] Suggestions mode (bot suggests moves without playing)

### Deliverables:
- ✅ Bot AI works
- ✅ Can play bot vs. bot
- ✅ Can play human vs. bot
- ✅ Bot suggestions available

---

# PART 8: KEY ARCHITECTURAL BENEFITS

## Security
- **No cheating**: All validation server-side
- **Hidden information**: Client never sees opponent's hand
- **Authentication**: Users logged in, verified
- **Action audit trail**: All actions logged

## Scalability
- **Horizontal**: Add more backend servers
- **Concurrent games**: Each game runs independently
- **Multi-region**: Deploy servers in different regions
- **Database**: Can grow as user base grows

## User Experience
- **Web-based**: Access from browser (any device)
- **Real-time**: WebSocket updates (no polling)
- **Responsive**: Updates reflect immediately
- **Offline graceful**: Reconnect if connection drops

## Development
- **Separation of concerns**: Client (UI) vs. Server (Logic)
- **Testable**: Rules engine is testable on server
- **Extensible**: Can add features (Discord integration, stats, etc.)

---

# CONCLUSION

Server-Client Web Architecture:
1. ✅ Enables multiplayer (crucial for MVP)
2. ✅ Web-based UI (better than CLI)
3. ✅ Secure (validation server-side)
4. ✅ Scalable (multiple users)
5. ✅ Professional (proper architecture)
6. ✅ Extensible (easy to add features)

**Next**: Start Phase 1 (Backend + Frontend setup).
