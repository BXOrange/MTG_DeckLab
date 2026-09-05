# DeckLab: MVP Use Cases (Revised)

---

# STRATEGIC SHIFT

Original MVP fokussierte auf **automatische Analyse & Simulation**:
- Win Condition Detection (Heuristiken)
- Consistency Scoring (Statistik-Modell)
- 10-Zug Simulation
- Automatische Empfehlungen

**Revised MVP fokussiert auf Spielbarkeit & LLM-Intelligence**:
- Regelkorrektheit als Fundament
- Mensch-lesbare Spiele (nicht Simulation)
- LLM für Analyse statt Heuristiken
- Schrittweise Automatisierung

**Kern-Einsicht:** Ein Regelwerk, das Menschen spielen können, ist wertvoller als eine Simulation, die Spieler nicht verstehen.

---

# PART 1: REVISED USE CASES

## USE CASE 1: Deckliste Laden & Validieren

### Description
System empfängt eine Commander-Deckliste und validiert sie gegen offizielle Regeln.

### Actor
Benutzer (CLI oder Datei-Upload)

### Preconditions
- Deckliste liegt vor (Text, Datei, oder String)
- Kartendatenbank verfügbar

### Main Flow
1. System parsed Deckliste (verschiedene Formate)
2. System validiert gegen Commander-Regeln:
   - Legendary Commander
   - Singleton Format (max 1 Kopie außer Basic Lands)
   - 100 Karten Total
   - Color Identity Constraint
   - Ban List
   - Partner Rules (falls vorhanden)
3. System resolved Kartennamen gegen Kartendatenbank
4. System lädt vollständige Kartinformationen
5. System gibt Validierungsergebnis: Legal / Illegal + Fehler

### Postconditions
- Deckliste ist geladen und validiert
- Legal-Status ist bekannt
- Alle Kartinformationen sind verfügbar
- Bei Fehlern: Klare Fehlermeldung mit Korrektur-Vorschlag

### Requirements (Architektur)
- **Parser**: Verschiedene Input-Formate
- **Validator**: Commander-Regeln (Legendary, Singleton, Color Identity, Ban List, Partner)
- **Card DB**: Vollständige Kartinformationen + Legality Tracking
- **Error Handling**: Aussagekräftig, mit Suggestions

---

## USE CASE 2: Deckliste durch LLM Analysieren

### Description
System nutzt ein LLM (Claude, etc.) um die Deckliste zu analysieren: Strategie, Win Conditions, Archetype, Deck-Kohärenz.

### Actor
System (LLM-powered)

### Preconditions
- Deckliste vollständig geladen und validiert
- LLM API verfügbar
- Alle Kartinformationen geladen

### Main Flow
1. System erstellt strukturierte Kartenliste:
   - Gruppiert nach Karttyp
   - Mit Mana-Kosten, Power/Toughness, Key Abilities
2. System sendet an LLM mit Prompt:
   ```
   "Analyze this Commander deck:
   [Deck List mit Struktur]
   
   Provide:
   1. Primary Win Conditions (Combat/Burn/Combo/Mill/Other)
   2. Deck Archetype (Aggro/Midrange/Control/Combo/Ramp/Other)
   3. Key Synergies (welche Karten interagieren?)
   4. Deck Cohesion Score (0-10: Wie rein ist die Strategie?)
   5. Win Condition Probability (Early/Mid/Late game)
   6. Potential Issues (Zu viele/wenige Threats? No removal? etc.)
   "
   ```
3. LLM analysiert und gibt strukturierte Antwort
4. System parst LLM Output und speichert Ergebnisse
5. System zeigt Analyse Benutzer

### Postconditions
- Deck-Strategie ist analysiert
- Win Conditions sind identifiziert
- Potential-Probleme sind aufgezeigt
- Alle Ergebnisse sind in strukturierter Form verfügbar

### AI Quality Benefits
- LLM versteht Card Text viel besser als Heuristiken
- LLM kann Synergien erkennen (z.B. "This creature triggers when enchantment enters")
- LLM kann nuancierte Analyse machen (z.B. "This is not pure Aggro, it's Tempo")
- Ergebnisse sind für Menschen lesbar und verständlich

### Requirements (Architektur)
- **LLM Integration**: API-Call zu Claude/GPT/etc.
- **Prompt Engineering**: Strukturierte Prompts für Deck-Analyse
- **Output Parsing**: JSON/Structured Output vom LLM
- **Caching**: Cache LLM-Responses (teuer, gleiche Decks wiederkehren)
- **Fallback**: Was tun wenn LLM offline?

### Note on LLM vs. Heuristics
LLM ist bessere Wahl als Heuristiken weil:
- Card Text ist komplex (LLM liest besser)
- Synergien sind nicht-trivial
- Spieler verstehen LLM-Reasoning besser
- Wartung ist einfacher (keine neuen Heuristiken)
- Error Rate ist akzeptabel für "advisory" tool (nicht kritisch)

---

## USE CASE 3: Goldfisch-Modus (Solo-Spiel)

### Description
Benutzer spielt eine Hand-Simulation gegen die echten MTG-Regeln (aber ohne Gegner).

### Actor
Benutzer (Mensch)

### Preconditions
- Deckliste validiert
- Regelwerk implementiert
- Game State kann getrackt werden

### Main Flow
1. System initialisiert Spiel:
   - Shuffled Deck
   - Zieht 7 Karten (Opening Hand)
2. Benutzer sieht:
   - Opening Hand
   - Mulligan Option
3. Falls Mulligan: Repeat, sonst beginn Spiel
4. Für jeden Zug:
   - **System**: Führt automatische Schritte aus
     - Untap Step
     - Draw Step
     - Resolve Triggered Abilities
   - **Benutzer**: Macht Decisions
     - "Cast Spell" (System validiert Legality)
     - "Activate Ability"
     - "Attack" (wenn vorhanden)
     - "Pass Priority"
   - **System**: Resolves Actions nach Regeln
     - Validiert Mana-Kosten
     - Aktualisiert Game State
     - Triggert Abilities
     - Managet Stack
5. Spiel läuft bis Benutzer "Stop" drückt
6. System zeigt finale Game State

### Postconditions
- Benutzer hat eine komplette Goldfisch-Runde gespielt
- Alle Züge sind nach echten Regeln aufgelöst worden
- Game State ist korrekt (Lands, Mana, Creatures, Hand, etc.)

### UI/UX Implications
- Muss lesbar & navigierbar sein
- Clear "What can I do now?" Display
- Easy Mulligan Interface
- Clear Spell Targeting System

### Requirements (Architektur)
- **Full Game Engine**: Alle MTG Regeln implementiert
- **Game State Display**: CLI oder Web-UI
- **Input Validation**: Nur legale Moves erlaubt
- **Stack Resolution**: Korrekt nach RULE 608
- **Mulligan Logic**: Benutzer wählt Keep/Mulligan
- **Error Messages**: Klar warum eine Action nicht funktioniert ("You need Blue mana for this spell")

---

## USE CASE 4: Multiplayer-Modus (2 Menschliche Spieler)

### Description
Zwei Benutzer spielen gegeneinander nach echten MTG-Regeln, unterstützt durch das System.

### Actor
2 Benutzer (Spieler 1 & Spieler 2)

### Preconditions
- Beide Decks validiert
- Regelwerk implementiert
- System kann Multiplayer-Game State managen

### Main Flow
1. System initialisiert Spiel:
   - Beide Decks shuffled
   - Beide Spieler ziehen 7 Karten
2. Mulligan Phase (standard):
   - Spieler 1 Keep/Mulligan
   - Spieler 2 Keep/Mulligan
   - Repeat bis beide Halten
3. Spiel läuft Turn für Turn:
   - Active Player (Sp1 Turn 1):
     - Untap, Draw, Main Phase I, Combat, Main Phase II, End
     - System managt alle Regeln
     - Sp1 macht Decisions (Cast Spell, Attack, etc.)
   - Non-Active Player (Sp2):
     - Kann reagieren (Instants, Activated Abilities)
     - Priority wenn nötig
   - Stack resolves nach Regeln
4. Nach Sp1's Turn: Sp2's Turn
5. Spiel läuft bis jemand:
   - Auf 0 or negative Life geht
   - Deck ist leer (Draw X from empty library)
   - Andere Loses Condition

### Postconditions
- Spiel wurde komplett nach Regeln gespielt
- Ein Gewinner ist bekannt
- Game History verfügbar

### Interaction Model
- Turn-basiert (nicht real-time)
- System trackt Priority + wer kann was tun
- Clear prompts: "Spieler 2, können Sie reagieren?" mit Timeout (z.B. 10 sec)
- Detailed Game Log

### Requirements (Architektur)
- **Full Game Engine**: Multiplayer-States, Priority System
- **Priority Tracking**: Wer hat Priority? Wer kann reagieren?
- **Timeout System**: Gegner sollten nicht ewig zögern können
- **Game Log**: Alle Actions protokolliert
- **Network** (falls nicht lokal): Support für remote Players
- **UI**: Beide Spieler sehen relevante Informationen (nicht Gegners Hand!)

---

## USE CASE 5: Automatisierte Züge (Bot)

### Description
System spielt automatisch Züge (statt Benutzer manuell jede Action einzugeben).

### Actor
System (AI/Bot)

### Preconditions
- Goldfisch-Modus oder Multiplayer läuft
- Spieler hat "Bot" Mode für seinen Deck gewählt

### Main Flow
1. Benutzer wählt vor Spiel: "Bot Play" oder "Manual Play"
2. Falls Bot:
   - System macht alle Decisions automatisch
   - Verwendet heuristische/strategische AI
3. Bot's Turn:
   - System evaluiert verfügbare Actions
   - Wählt beste Action (greedy oder more sophisticated)
   - Spielt Action
   - Loop bis Main Phase vorbei
4. Benutzer sieht alle Bot-Actions in real-time
5. Nach Bot-Turn: Benutzer/anderer Bot spielen

### Bot Strategy (MVP Level)
**Greedy Strategy:**
- Priorität 1: Spielen Win Condition wenn möglich
- Priorität 2: Spielen beste Threat (nach Power oder Utility)
- Priorität 3: Spielen beste Removal (gegen gegnerische Threats)
- Priorität 4: Spielen beste Draw/Acceleration
- Priorität 5: Pass

**Better Strategy (später):**
- Lookahead (T+1 planning)
- Monte Carlo evaluation
- Threat assessment (gegnerisches Deck)

### Postconditions
- Bot spielte jeden Zug vollständig aus
- Alle Actions sind korrekt nach Regeln
- Spiel ist spielbar Bot vs. Bot oder Bot vs. Mensch

### Requirements (Architektur)
- **AI/Decision Engine**: Bot Strategy Implementation
- **Action Evaluation**: Score für jede mögliche Action
- **Threat Assessment**: Was ist gegnerisches Threat Level?
- **Logging**: Was hat Bot warum gemacht? (für Learning)

---

# PART 2: ARCHITECTURE IMPACT

## What Changed from Original MVP?

### REMOVED Requirements (Not in MVP)
- ❌ Consistency Scoring / Probability Calculation
- ❌ 10-Turn Simulation & Stats Collection
- ❌ Sensitivity Analysis (which cards matter)
- ❌ Recommendation Engine
- ❌ Mulligan Heuristics (Benutzer wählt)

### ADDED Requirements (New MVP)
- ✅ **Full Game Engine** (Was wichtiger als Simulation)
- ✅ **UI/CLI for Playing** (Muss spielbar sein)
- ✅ **LLM Integration** (Statt Heuristiken)
- ✅ **Multiplayer Support** (Nicht nur Single Player)
- ✅ **Priority System** (Wichtig für Mensch vs. Mensch)
- ✅ **Timeout/Turn Management** (Für Multiplayer)

### Architecture Layers (Revised)

```
Layer 5: UI/Game Interface
         (CLI or Web for Human Players)
         
Layer 4: Game Engine (Core)
         Turn Loop, Phase Loop, Priority, Stack, State
         
Layer 3: Rules Engine
         RULE 601/602/603/608/607/504 + Commander-Specific
         
Layer 2: Card Services
         Card Effect Implementation
         
Layer 1: Data Layer
         Card DB, Deck Storage, Game State
         
Parallel: LLM Integration
          (For Deck Analysis, UC2)
```

---

## Key Architectural Changes

### 1. Game Engine ist jetzt CENTRAL (nicht optional)
**Alte MVP**: Simulation war the main thing
**Neue MVP**: Game Engine ist the foundation, alles andere hängt daran

**Implication**: 
- Muss absolut regelkorrekt sein
- Muss Performance haben (aber kein 1000 games/sec nötig)
- Muss Human-Readable Output haben

### 2. LLM statt Heuristiken
**Alte MVP**: Consistency Scoring, Win Condition Detection, Archetype Detection = Heuristiken
**Neue MVP**: LLM macht das alles in UC2

**Implication**:
- Weniger komplexer Code nötig
- Aber externe API Abhängigkeit
- Höhere Fehlerrate akzeptabel (advisory, nicht critical)

### 3. UI ist Anforderung (nicht nice-to-have)
**Alte MVP**: CLI nur für Report
**Neue MVP**: CLI muss Spiel spielbar machen

**Implication**:
- Komplexere UI-Logic nötig
- Game State Display muss klar sein
- Input Validation muss freundlich sein

### 4. Multiplayer-State ist komplexer
**Alte MVP**: Nur single-player Simulation
**Neue MVP**: Two Player Games mit Priority System

**Implication**:
- Priority Tracking (wer darf was tun?)
- Timeout Management (Gegner macht kein Move?)
- Game Log für Disputes
- Concurrent Actions (beide Spieler simultane Triggers)

---

# PART 3: REVISED ARCHITECTURE REQUIREMENTS

## Requirement Category 1: Data Layer (Mostly Same)

### R1.1: Card Database
- All MTG cards (min 2000)
- Name, Mana Cost, Type, Power/Toughness, Abilities, Rules Text
- Legendary Status, Partner Status
- Color Identity
- Scryfall Integration

### R1.2: Deck Storage (Commander Format)
- 100 Card Singleton (1 Commander + 99 Deck)
- Color Identity Validation
- Ban List Checking
- Legal Status

### R1.3: Game State (New Requirements)
- **Zones**: Hand, Library, Graveyard, Battlefield, Stack, Exile, Command Zone
- **Player State**: Life, Mana Pool, Priority, "is Active Player?"
- **Stack State**: Order of Spells/Abilities, resolved/unresolved status
- **Turn State**: Current Phase, Current Step, Turn Number
- **Triggered Abilities**: Pending triggers, condition met?
- **Continuous Effects**: What's active right now (auras, etc.)

---

## Requirement Category 2: Rules Engine (CRITICAL Now)

### R2.1: Phase Structure (RULE 500)
```
Main Loop:
  While not game_end:
    Active Player's Turn:
      1. Beginning Phase
         - Untap Step
         - Upkeep Step (resolve triggered abilities)
         - Draw Step
      2. Main Phase I
         - Play Land (if haven't)
         - Cast Spells / Activate Abilities
      3. Combat Phase
         - Declare Attackers (if want)
         - Opponent Declares Blockers (if can)
         - Resolve Combat Damage
      4. Main Phase II
         - Same as Main I
      5. Ending Phase
         - Cleanup Step
    Non-Active Player's Turn:
      - Can respond with Instants
      - Can activate Abilities (if timing ok)
```

### R2.2: Casting Rules (RULE 601)
- Instant: Any time has priority
- Sorcery: Main phase only, active player
- Creature/Permanent: Like sorcery
- Mana cost must be paid
- Target selection if required

### R2.3: Stack Resolution (RULE 608)
- LIFO ordering
- Each spell/ability resolves individually
- Triggered abilities generated during resolution go on stack
- If spell becomes illegal, it's countered

### R2.4: Priority System (RULE 117)
**CRITICAL for Multiplayer:**
- Active player gets priority first (after drawing, etc.)
- Spells/Abilities go on stack
- Other player can respond (cast Instant, etc.)
- Back to active player
- If stack empty and no one passes, game continues
- If both pass with stack empty, current step/phase ends

### R2.5: Triggered Abilities (RULE 603, 607)
- Ability triggers when condition occurs
- Goes on stack (after state-based actions)
- If multiple trigger same time: Active player orders (RULE 607.1)
- Resolve when it's time (after other spells)

### R2.6: Mana System (RULE 504)
- Mana pool per player
- Tap land for mana
- Mana colors (W/U/B/R/G/C)
- Casting requires sufficient mana
- Color identity constraint (Commander)
- Mana pool empties at end of phase

### R2.7: Combat (RULE 500.2 - Combat Phase)
**Can be simplified for MVP:**
- Declare attackers (which creatures attack)
- Defender declares blockers (which creatures block)
- Resolve combat damage
- Creatures with abilities trigger

### R2.8: State-Based Actions (RULE 704)
**Simplified for MVP:**
- Legendary rule (duplicate legendaries → graveyard)
- Aura Enchantment rule (if attached creature gone → aura to graveyard)
- 0 Toughness → graveyard
- 0 or less life → lose game
- Other edge cases

---

## Requirement Category 3: Card Effect Services

### R3.1: Generic Card Effects
- Damage (Deal X damage to target)
- Draw (Draw X cards)
- Discard (Put X cards from hand to graveyard)
- Search (Search deck for card matching criteria)
- Destroy (Destroy target creature/permanent)
- Counter (Counter target spell)
- Pump (Creature gets +X/+X until end of turn)
- Mana Production (Add mana to pool)

### R3.2: Service Registration
- Each card service registers for events it cares about
- Events: SPELL_CAST, SPELL_RESOLVES, CREATURE_ENTERS, DAMAGE, etc.
- Services subscribe to relevant events

---

## Requirement Category 4: Game Engine (NEW, Critical)

### R4.1: Game Loop
- Turn progression
- Phase progression
- Step progression
- Event triggering

### R4.2: Priority Management (NEW)
- Track who has priority
- Validate legal actions based on priority
- Pass priority correctly
- Concurrency handling (simultaneous triggers)

### R4.3: Action Validation (NEW)
- Is this spell castable right now?
- Do I have enough mana?
- Can I target this?
- Does it follow current phase restrictions?

### R4.4: Player Interaction (NEW)
- Accept moves from Benutzer
- Timeout for slow players
- Error messages when illegal
- Undo? (Maybe not for MVP)

---

## Requirement Category 5: LLM Integration

### R5.1: LLM API Integration
- Call Claude/GPT/etc. API
- Structured prompts
- Structured output parsing

### R5.2: Deck Analysis Prompts
- Structured deck representation
- Ask for: Win Conditions, Archetype, Synergies, Issues
- Parse JSON/structured responses

### R5.3: Caching
- Cache results for same decks (expensive!)
- Store analysis with deck

---

## Requirement Category 6: UI/Interface (NEW, Critical)

### R6.1: CLI Interface
- Display current game state (clear, readable)
- Display player's options ("What can you do?")
- Input for player actions ("Cast spell", "Attack", etc.)
- Display results of actions

### R6.2: Game State Display
- Battlefield (creatures, other permanents)
- Hand (player's cards)
- Stack (current spells/abilities)
- Life totals
- Mana pool
- Graveyard/Exiled
- Turn/Phase info

### R6.3: Input Handling
- "Play Spell X"
- "Target Y with Spell"
- "Attack with creature Z"
- "Activate ability"
- "Pass" / "Done"
- "Mulligan" / "Keep"

### R6.4: Error Messages
- Why can't I cast this? (Mana? Timing? Color Identity?)
- Clear, helpful messages
- Suggestions for legal moves

---

# PART 4: WHAT'S NOT IN MVP

### ❌ Consistency Scoring
- Was Teil des alten MVP
- Jetzt: LLM macht das

### ❌ Sensitivity Analysis
- War für Upgrade-Empfehlungen
- Nicht nötig für MVP

### ❌ Recommendation Engine
- Wurde durch LLM ersetzt

### ❌ Mulligan Heuristics
- Benutzer entscheidet selbst

### ❌ 10-Turn Simulation Statistics
- War nicht-essential
- Game Engine ist important

### ❌ Performance (1000 games/sec)
- Nicht relevant (keine Simulation)
- ~10-20 games/day ist OK

---

# PART 5: MVP PHASES

## Phase 1: Rules Infrastructure (Weeks 1-2)
- Card DB + Parser
- Game State Model
- Phase/Step Structure

## Phase 2: Core Rules Engine (Weeks 3-4)
- Casting (RULE 601)
- Stack (RULE 608)
- Mana System (RULE 504)
- Priority (RULE 117)

## Phase 3: Game Loop (Weeks 5-6)
- Turn/Phase Loop
- Action Validation
- Event System

## Phase 4: UI/Playing (Weeks 7-8)
- CLI Interface
- Game State Display
- Player Input

## Phase 5: Multiplayer (Weeks 9-10)
- Two Player Support
- Priority Management
- Timeout System

## Phase 6: LLM Analysis (Weeks 11-12)
- LLM Integration
- Prompt Engineering
- Output Parsing

## Phase 7: Bot AI (Weeks 13-14)
- Bot Decision Engine
- Greedy Strategy
- Play Automation

---

# CONCLUSION

**Revised MVP is fundamentally different:**

| Aspect | Original MVP | Revised MVP |
|--------|-------------|------------|
| **Focus** | Deck Analysis & Simulation | Playable Game Engine |
| **Complexity** | Heuristics + Statistics | Correct Rules Implementation |
| **LLM Role** | Optional | Core (for analysis) |
| **Play Experience** | None (analysis only) | Can play actual games |
| **AI** | For simulation | For bot players |
| **Value** | Recommendations | Playable Magic Sim |

**Why this is better:**
1. **Fundament First**: Correct rules engine is more valuable than any analysis
2. **LLM-Powered**: Analysis by LLM is better than hand-coded heuristics
3. **Human-Playable**: Actual games are more useful than reports
4. **Scalable**: Can add features (Commander 1v1, etc.) without rewriting
5. **Testable**: Rules can be tested against actual MTG games

**Critical Success Factor**: Rules Engine MUST be correct. Everything else depends on it.
