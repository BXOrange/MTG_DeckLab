# MTG Deck Analyzer: Use Cases & Architecture Requirements

---

# PART 1: USE CASES (aus ursprünglicher Anfrage extrahiert)

## Original-Anfrage zusammengefasst:

"AI-unterstütztes Analysewerkzeug für Magic Decks. Input: Deckliste (Commander-Format). Funktionen: Winconditions ableiten, Spielplan evaluieren, erste 10 Züge simulieren, Konsistenz bewerten (intern + Störeinflüsse). Output: Konsistenz-Score, Verbesserungsvorschläge, Upgrades."

---

## USE CASE 1: Deckliste Laden & Validieren

### Description

System empfängt eine Commander-Deckliste und validiert sie gegen offizielle Commander-Regeln.

### Actor
Benutzer (über CLI oder API)

### Preconditions

- Deckliste liegt vor (Text, Datei oder String)
- Format ist erkannt
- Kartendatenbank verfügbar

### Main Flow

1. Benutzer gibt Deckliste ein
2. System parsed Format und extrahiert:
   - Commander Karte(n)
   - 99 Deck-Karten
3. System validiert Commander:
   - **Legendary Check**: Commander muss legendär sein
   - **Partner Check**: Falls "Partner" oder "Partner with" Ability
     - Mit "Partner": Kann mit einem anderen Partner-Commander kombiniert werden
     - Mit "Partner with X": Muss mit spezifischer Karte X gepairt sein
   - **Planeswalker Exception**: Bestimmte Planeswalker können Commander sein
4. System validiert Deck gegen Commander-Regeln:
   - **Singleton**: Exakt 1 Kopie jeder Karte (außer Basic Lands, beliebig viele erlaubt)
   - **Total Kards**: Exakt 100 Karten (1 Commander + 99 Deck-Karten)
   - **Color Identity**: Alle Karten müssen in der Farb-Identität des Commanders sein
     - Farb-Identität = alle Mana-Symbole in der Karten-Text + Mana-Kosten
     - Z.B. Commander "Izzet Spell Slinger" (U/R) → Deck darf nur U/R/farblos Karten haben
   - **Ban List**: Keine gebannten Karten im Deck
5. System resolved Kartennamen gegen Kartendatenbank
6. System lädt vollständige Kartinformationen für alle Karten
7. System parsed Commander spezifische Attribute:
   - Commander Abilities
   - Partner Status (falls vorhanden)
   - Color Identity für Validierung

### Postconditions

- Deckliste ist im System geladen
- Commander ist identifiziert und validiert
- Alle 100 Karten haben korrespondierende Card-Objekte
- Kartinformationen sind verfügbar (Mana-Kosten, Typ, Fähigkeiten, Legality)
- Color Identity ist berechnet und validiert
- Deck ist gegen Commander-Rules validiert (keine Fehler)

### Error Handling

- Commander nicht legendär → Fehler
- Duplicate Karten (>1 Kopie außer Lands) → Fehler
- Card nicht in Color Identity → Fehler
- Card ist auf Ban List → Fehler
- Unbekannte Kartennamen → Fehler mit Suggestion
- Nicht exakt 100 Karten → Fehler

### Requirements (Architektur-Implikationen)

- **Data Layer**: Kartendatenbank mit:
  - Card Name, Mana Cost, Type, Abilities, Oracle Text
  - Legendary Status, Partner Status
  - Color Identity berechnung
  - Ban List Status (aktuell)
- **Parser Layer**: Verschiedene Eingabe-Formate:
  - "4x Lightning Bolt" Format
  - "Lightning Bolt x4" Format
  - Archidekt-Format
  - MTGArena-Format
- **Validator Layer**: Commander-spezifische Validierung:
  - Legendary + Partner Checking
  - Singleton Checking
  - Color Identity Constraint
  - Ban List Checking
  - Total Card Count
- **Color Identity Engine**: Berechnung der Farb-Identität
- **Error Handling**: Aussagekräftige Fehler mit Suggestions

---

## USE CASE 2: Win Conditions Ableiten

### Description

System analysiert die Deckliste und identifiziert die primären Gewinn-Bedingungen des Decks.

### Actor

System (automatisch nach Deckliste-Load)

### Preconditions

- Deckliste vollständig geladen
- Alle Kartinformationen verfügbar

### Main Flow

1. System durchsucht Deck nach "Win Condition" Karten
   - Defs Win Condition: Karte, die eine Spieler in einen gewinnenden Zustand bringt
   - Beispiele: "Creatures mit Power >= 3", "Burn-Spells", "Combo-Pieces"
2. System kategorisiert Win Conditions nach Typ:
   - **Combat-Win**: Creatures angreifen
   - **Burn-Win**: Direkter Damage
   - **Combo-Win**: Spezifische Kartenkombinationen
   - **Mill-Win**: Gegner Deck aufgebraucht
   - **Other-Win**: Andere Mechnaiken (z.B. Poison Counter)
3. System ordnet nach Häufigkeit/Macht
4. System identifiziert "Primary Win Condition" (am wahrscheinlich in frühem Spiel)

### Postconditions

- Win Conditions sind kategorisiert
- Jede Win Condition hat einen Score (Wahrscheinlichkeit, Effektivität)
- System kennt "Plan A" des Decks

### Requirements (Architektur-Implikationen)

- **Heuristic Layer**: Win Condition Detection basierend auf Kartenattributen
- **Scoring System**: Wie "wichtig" ist jede Win Condition?
- **Pattern Recognition**: Identifiziere Combo-Pieces
- **Data Model**: Win Condition als erste-Klasse-Objekt

---

## USE CASE 3: Spielplan Evaluieren

### Description

System bewertet den logischen Aufbau des Spielplans und dessen Kohärenz.

### Actor

System (automatisch)

### Preconditions

- Deckliste geladen
- Win Conditions identifiziert

### Main Flow

1. System identifiziert Deck-Archetype basierend auf Karten:
   - Aggro: Viele billige Creatures
   - Midrange: Mittelteure Creatures + Interaction
   - Control: Viele Removal/Counterspells + Draw
   - Combo: Specific card interactions
   - Ramp: Mana acceleration
2. System validiert Konsistenz des Spielplans:
   - Passen Karten zur Strategie?
   - Gibt es Outliers? (z.B. großer Threat in Aggro-Deck)
   - Sind Synergien vorhanden?
3. System prüft ob Spielplan die Win Conditions unterstützt:
   - Gibt es Enabler? (z.B. Tutors für Combo-Win)
   - Gibt es Acceleration? (z.B. Mana-Ramp für große Threats)
   - Gibt es Interaction? (z.B. Removal gegen gegnerische Threats)
4. System scores:
   - Archetype Clarity (Wie rein ist die Strategie?)
   - Synergy Level (Wie viel interagieren Karten?)
   - Win Condition Support (Wie gut unterstützt Deck die Win-Conditions?)
   - Interaction Quality (Ist Removal/Counterspells gut?)

### Postconditions

- Spielplan ist bewertet
- Mögliche Probleme sind identifiziert
- System versteht Deck-Archetype

### Requirements (Architektur-Implikationen)

- **Pattern Recognition**: Archetype Detection
- **Scoring System**: Mehrere Dimensionen (Clarity, Synergy, Support, Interaction)
- **Relationship Tracking**: Welche Karten interagieren miteinander?
- **Heuristic Engine**: Was ist "guter" Spielplan?

---

## USE CASE 4: 10-Zug Simulation

### Description

System simuliert die ersten 10 Züge des Spiels automatisch.

### Actor

System (simuliert beide Spieler, aber fokussiert auf primären Spieler)

### Preconditions

- Deckliste geladen
- Regelwerk implementiert
- Game State kann tracking werden

### Main Flow

1. System shuffled Deck
2. System führ Mulligan durch:
   - Zieht 7 Karten (Hand)
   - Bewertet Hand-Qualität (RULE 110.4: Hand-Größe)
   - Mulligan wenn nötig (nach heuristischen Regeln)
3. System simuliert 10 Züge:
   - Für jeden Zug:
     - Beginning Phase (Draw, Untap)
     - Main Phase I
     - Combat Phase (optional, meist disabled für MVP)
     - Main Phase II
     - Ending Phase
     - Cleanup Phase
   - Während jedes Zugs:
     - Spieler spielt beste Spells (greedy AI)
     - Stack resolves Spells und Abilities in korrekter Reihenfolge
     - Mana wird bezahlt
     - Creatures/Enchantments/etc. sind im Spielfeld
4. System recorded Daten für jeden Zug:
   - Handgröße
   - Lands im Spielfeld
   - Spells gecastet
   - Creatures im Spielfeld
   - Mana verfügbar
   - Life total

### Postconditions

- 1000 vollständige Spiele simuliert
- Statistiken für jeden Zug aggregiert
- Durchschnitt/StdDev berechnet

### Requirements (Architektur-Implikationen)

- **Game Engine**: Vollständiger Spielablauf
- **Rule System**: Regel 601 (Casting), 608 (Stack), 607 (Triggers), 504 (Mana), etc.
- **AI System**: Spell selection (greedy oder sophisticated?)
- **Mulligan Logic**: Hand-Evaluation
- **Performance**: >1000 games/sec (sonst zu langsam)
- **Statistics**: Collection der Rohdaten

---

## USE CASE 5: Konsistenz Bewertung (Intern)

### Description
System bewertet wie "konsistent" das Deck in sich selbst ist.

### Actor
System (Analyzer)

### Preconditions

- Deckliste geladen
- Simulation durchgeführt (10-Zug Daten)
- Win Conditions definiert

### Main Flow

1. System analysiert "mana curve":
   - Wie ist Mana-Kosten verteilt?
   - Score: Ideal ist glockenförmig, z.B. für Aggro Low, für Control High
2. System berechnet "Konsistenz der Win Condition":
   - Hypergeometrische Verteilung: P(haben Win Condition by Turn N)
   - Für Turn 3, 5, 7, 10
   - Score: Higher Probability = Higher Score
3. System analysiert "Redundanz":
   - Wie viele Kopien von Key-Effekten?
   - Z.B. "4x Tutor effekt" vs "1x Tutor"
   - Score: Redundant = weniger Variance
4. System analysiert "Interaction":
   - Wie viele Removal/Counterspells im Deck?
   - Sind sie gegen wahrscheinliche Threats geignet?
   - Score: Balanced (nicht zu viel, nicht zu wenig)
5. System scores Gesamtkonsistenz:
   - Mana Curve Score (20%)
   - Win Condition Probability (40%)
   - Redundancy Score (20%)
   - Interaction Score (20%)
   - **Total: 0-100 Score**

### Postconditions

- Konsistenz-Score berechnet
- Breakdown nach Kategorien verfügbar
- Schwachstellen identifiziert

### Requirements (Architektur-Implikationen)

- **Statistics Engine**: Hypergeometrische Wahrscheinlichkeit
- **Scoring System**: Multi-dimensional scoring
- **Win Condition Tracking**: Welche Karten sind Win Conditions?
- **Data Aggregation**: Von Sim-Daten zu Scores

---

## USE CASE 6: Konsistenz Bewertung (Extern / Störeinflüsse)

### Description

System bewertet wie "robust" das Deck gegen externe Störeinflüsse ist (gegnerische Interactions, schlechte Draws).

### Actor

System (Analyzer)

### Preconditions

- Simulation durchgeführt
- Interne Konsistenz berechnet

### Main Flow

1. System modelliert "Mulligan Impact":
   - Simuliert Spiele mit 0, 1, 2, 3 Mulligans
   - Berechnet wie sehr jeder Mulligan die Konsistenz reduziert
   - Score: Weniger Verlust = höher
2. System modelliert "Draw Variance":
   - Über 1000 Runs: Wie konsistent ist Draw-Order?
   - StdDev von "Can cast X on Turn Y"
   - Score: Niedrige Variance = höher
3. System modelliert "Removal Impact":
   - Wenn gegnerischer Player ein Key-Card removet, was passiert?
   - Z.B. "Wenn unser Win Condition countered wird, was ist Plan B?"
   - Score: Gute Backups = höher
4. System modelliert "Combo Fragility":
   - Wenn Combo-Piece removet wird, ist Deck nutzlos?
   - Score: Redundante Combos = höher
5. System berechnet "Robustness Score":
   - Mulligan Impact (25%)
   - Draw Variance (25%)
   - Removal Impact (25%)
   - Combo Fragility (25%)
   - **Total: 0-100 Score**

### Postconditions

- Robustness Score berechnet
- Deck-Schwächen gegen Störeinflüsse identifiziert
- Empfehlungen für "weniger fragile" Cards generiert

### Requirements (Architektur-Implikationen)

- **Sensitivity Analysis**: Welche Karten matter most?
- **Scenario Modeling**: "Was wenn gegnerischer Player X macht?"
- **Monte Carlo**: Variance berechnung
- **Backup Plan Detection**: Hat Deck Alternativ-Wege?

---

## USE CASE 7: Verbesserungsvorschläge Generieren

### Description

System schlägt konkrete Kartenwechsel vor um Konsistenz zu verbessern.

### Actor

System (Analyzer)

### Preconditions

- Alle vorherigen Analysen durchgeführt
- Scores berechnet
- Schwachstellen identifiziert

### Main Flow

1. System identifiziert "low-impact cards":
   - Entfernung welcher Karte erhöht Score am meisten?
   - Score Impact pro Karte berechnen
   - Top 10 "Kandidaten für Removal"
2. System identifiziert "gap cards":
   - Was fehlt zum Deck? Welche Effekte würden Score erhöhen?
   - Z.B. "Deck hat nur 2 Draw-Quellen, bräuchte 4"
   - Z.B. "Deck hat keine Removal, bräuchte 3-4"
3. System schlägt Swaps vor:
   - Für jede "low-impact" Karte:
     - Finde Replacement aus gleicher Mana-Kosten
     - Replacement adressiert Deck-Schwäche
     - Berechne neuer Score
     - Zeige Score-Verbesserung
4. System prioritized Swaps:
   - "Swap: Entferne X, füge Y hinzu → Score +3"

### Postconditions

- Top 5-10 Verbesserungsvorschläge generiert
- Jeder mit erwarteter Score-Verbesserung
- Realistic (nur legal cards, richtige Mana-Kosten)

### Requirements (Architektur-Implikationen)

- **Sensitivity Analysis Engine**: Impact pro Karte
- **Card Search**: "Finde Karte mit diesen Eigenschaften"
- **Legality Checker**: Ist Card legal?
- **Scoring Prediction**: Wie ändern sich Scores wenn Karte getauscht?

---

## USE CASE 8: Upgrade-Empfehlungen Generieren

### Description

System schlägt konkrete Premium-Upgrades vor (bessere Versionen bestehender Karten).

### Actor

System (Analyzer)

### Preconditions

- Verbesserungsvorschläge generiert
- Deck-Profile bekannt

### Main Flow

1. System identifiziert "upgradeable cards":
   - Welche Karten haben bessere Versionen?
   - Z.B. "Lightning Bolt" → "Unholy Heat" (mit möglichem Bonus)
   - Z.B. "Counterspell" → "Spell Pierce" (schwächer aber billiger)
2. System modelliert Upgrade-Impact:
   - Wenn Karte X durch bessere Version Y ersetzt wird
   - Berechne neuer Score
   - Berechne zusätzliche Mana-Kosten (wenn X günstiger war)
3. System prioritized Upgrades:
   - "Upgrade: Swap Verdant Catacombs für Scalding Tarn → Score +1.5"
   - "Upgrade: Swap Counterspell für Force of Will → Score +2"

### Postconditions

- Top 5-10 Upgrade-Vorschläge
- Jeder mit Score-Verbesserung
- Budgetaware (billig → teuer, oder ganz gratis?)

### Requirements (Architektur-Implikationen)

- **Card Relationship Graph**: "Welche Karten sind Upgrades voneinander?"
- **Price Data** (optional): Für Budget-Aware Recommendations
- **Upgrade Logic**: Wie beurteilt man "ist Y besser als X"?

---

# PART 2: ARCHITECTURE REQUIREMENTS (from Use Cases)

## Requirement Category 1: Data Layer

### R1.1: Card Database

- Speichert alle MTG Karten (mindestens 2000 für MVP)
- Attributes: 
  - Name, Mana-Kosten, Typ, Power/Toughness
  - Abilities, Rules Text (Oracle Text)
  - Legendary Status, Partner Status
  - Color Identity (berechnet aus Mana-Symbolen)
  - Set, Rarity, Card ID (Scryfall)
- Source: Scryfall API oder Local DB
- Performance: <100ms Lookup
- Updates: Commander Ban List tracking

### R1.2: Deck Storage (Commander-Format)

- Speichert eine komplette Commander-Deckliste (100 Karten)
- Struktur:
  - Commander (1 oder 2 mit Partner)
  - Main Deck (99 Karten)
  - Format: Singleton (max 1 Kopie außer Basic Lands)
- Mapping: Card → Quantity (max 1 oder unlimited für Basics)
- Color Identity: Berechnet und gespeichert
- Validation Status: Legal/Illegal + Error Messages
- Metadata: Deck Name, Format (Commander), Archetype (optional)

### R1.3: Game State

- Speichert aktuellen Spielzustand während Simulation
- Zones: Hand, Library, Graveyard, Battlefield, Stack, Exile
- Player state: Life, Mana Pool, Priority
- Performance: Kopieren für jeden Zug (1000 games)

---

## Requirement Category 2: Rules Engine

### R2.1: Casting Rules (RULE 601)

- Instant: Any time player has priority
- Sorcery: Main phase only
- Creatures/Permanents: Like sorcery
- Mana cost validation (absolut)
- **Commander-Specific**: Casting Commander from Command Zone (can be cast any time you have priority after first summon)

### R2.2: Stack Resolution (RULE 608)

- LIFO ordering
- Spell resolution
- Triggered ability resolution

### R2.3: Triggered Ability Ordering (RULE 607)

- Multiple triggers at same time
- Active player chooses order

### R2.4: Mana System (RULE 504)

- Mana production (tapping lands)
- Mana pool management
- Color requirements
- **Commander-Specific Color Identity**: Karte kann nur gecastet werden wenn Farben in Color Identity des Commanders sind

### R2.5: Card Effect Resolution

- Damage, Draw, Discard, Removal, etc.
- Generic enough for 100+ card effects

### R2.6: Commander-Specific Rules

- **Color Identity Constraint**: Alle Karten müssen in Color Identity des Commanders sein
  - Color Identity = alle Mana-Symbole in Mana-Kosten + Oracle Text
  - Z.B. wenn Commander ist "Izzet" (U/R), kann kein schwarzer Mana (B) im Deck sein
- **Command Zone**: Commander startet im Command Zone, kann gecastet werden
- **Partner Commanders**: Bis zu 2 Commander mit "Partner" oder "Partner with"
- **Legendary Rule**: Duplicate Legendaries go to graveyard (for simulation accuracy)

---

## Requirement Category 3: Game Engine

### R3.1: Game Loop

- Turn progression (10 turns)
- Phase progression (Begin → Main I → Combat → Main II → End)
- Event triggering (draw, cast spell, creature ETB, etc.)

### R3.2: AI/Decision Making

- Which spells to cast? (Greedy: highest impact)
- Which target? (AI logic)
- Mulligan decision? (Heuristic: hand quality)
- **Performance**: Must be fast (<1000 games/sec)

### R3.3: Mulligan Logic

- Evaluate hand quality
- Decide keep/mulligan
- Heuristic: lands, playables, win conditions

---

## Requirement Category 4: Analysis Engine

### R4.1: Win Condition Detection

- Identify primary win conditions
- Categorize (combat, burn, combo, mill, etc.)
- Score by likelihood

### R4.2: Archetype Detection
- Identify deck strategy (aggro, control, combo, etc.)
- Score how "pure" strategy is
- Detect mismatches

### R4.3: Consistency Scoring
- Mana curve analysis
- Win condition probability (hypergeometric)
- Redundancy score
- Interaction balance
- **Output**: 0-100 score

### R4.4: Robustness Scoring
- Mulligan impact
- Draw variance
- Removal impact
- Combo fragility
- **Output**: 0-100 score

### R4.5: Sensitivity Analysis
- Which cards matter most?
- Impact of removing card X
- Impact of adding card Y
- Ranking by importance

### R4.6: Recommendation Engine
- Suggest card swaps
- Suggest upgrades
- Prioritize by score improvement
- Realistic (legal, right mana cost, etc.)

---

## Requirement Category 5: Output/Reporting

### R5.1: Report Generation
- Consistency Score + Breakdown
- Robustness Score + Breakdown
- Archetype + Mismatches
- Top suggestions (5-10)
- Format: Text, JSON, or HTML

### R5.2: CLI Interface
- Input: Decklisten-Datei
- Options: --iterations, --format, --depth
- Output: Report
- Performance: <5 seconds total

---

# PART 3: ARCHITECTURAL DECOMPOSITION

## Layer 1: Data Layer

**Responsibility**: Store and retrieve card/deck information

- Card Database (Scryfall cache or local DB)
- Deck Parser (various input formats)
- Card Validator

## Layer 2: Rules Layer

**Responsibility**: Implement MTG rules as executable code

- Casting Validator (RULE 601)
- Stack Manager (RULE 608)
- Triggered Ability Resolver (RULE 607)
- Mana System (RULE 504)
- Card Effect Services (Damage, Draw, Discard, etc.)

## Layer 3: Game Engine Layer

**Responsibility**: Run 10-turn simulations

- Turn Loop
- Phase Loop
- Event Bus (coordinates rule events)
- AI Decision Maker
- Mulligan Evaluator
- Stats Recorder

## Layer 4: Analysis Layer

**Responsibility**: Analyze deck and generate scores/recommendations

- Win Condition Detector
- Archetype Detector
- Consistency Analyzer (R4.3)
- Robustness Analyzer (R4.4)
- Sensitivity Analyzer (R4.5)
- Recommendation Generator (R4.6)

## Layer 5: Output Layer
**Responsibility**: Format and deliver results

- Report Generator (R5.1)
- CLI Interface (R5.2)

---

# PART 4: CRITICAL DESIGN QUESTIONS

Before implementing, these must be answered:

## Q1: Card Effect Representation

How do we represent "Lightning Bolt deals 3 damage" and 100+ other effects in a unified way?

- Option A: Hardcoded services per card
- Option B: Generic effect engine + parameters
- Option C: Hybrid (common patterns in engine, rare in services)

## Q2: AI Decision Quality

"Greedy" AI (play highest impact spell) vs. more sophisticated?

- Trade-off: Accuracy vs. Performance
- For MVP: Greedy is probably OK (simple, fast)
- For Production: Might need Monte Carlo or similar

## Q3: Mulligan Heuristic

How do we evaluate "is this hand keepable"?

- Factors: Mana curve, playables, win condition accessibility
- Must match intuition of good player
- This affects simulation quality significantly

## Q4: Scope of Rules Implementation

Do we implement EVERY rule or strategic subset?

- Full Comprehensive Rules: Too much
- Strategic subset: What's the minimum viable set?
- Suggestion: Focus on rules that affect deck consistency analysis

## Q5: Performance Budget

1000 games per second is aggressive. Is that realistic?

- Python: Probably 100-500 games/sec
- Pypy/Cython: Maybe 1000+
- Trade-off: Speed vs. Dev velocity

---

# PART 5: DEPENDENCIES MATRIX

Which Use Cases depend on which?

```code
UC1 (Load Deck)
  ↓
  ├─ UC2 (Win Conditions) ──────┐
  ├─ UC3 (Evaluate Plan) ───────┤
  └─                             ├─ UC4 (Simulate)
                                 │     ↓
                          ┌──────┴─────────┬─────────┐
                          ↓                ↓         ↓
                    UC5 (Consistency) UC6 (Robustness)
                          ↓                ↓
                          └────────┬───────┘
                                   ↓
                        UC7 (Suggestions)
                              ↓
                        UC8 (Upgrades)
```

**Critical Path**: UC1 → UC2 → UC4 → UC5 → UC7

---

# CONCLUSION

Before writing code, we have:

1. ✅ Extracted 8 Use Cases from original request
2. ✅ Defined Requirements for each Use Case
3. ✅ Decomposed into 5 Layers
4. ✅ Identified Critical Design Questions
5. ✅ Mapped Dependencies

**Next Step**: Answer critical design questions → Architecture design → Implementation plan.

---

# APPENDIX: Commander Format Rules Ref

## Official Commander Rules (Summary)

### Deck Construction

- **Format**: 100 Card Singleton (Commander included)
- **Commander**: 1-2 Legendary Creatures/Planeswalkers/etc. in Command Zone
  - Commander must be legendary creature, planeswalker, or have "can be your commander" ability
  - Default commander capacity: 1 card
  - With "Partner" ability: Can have 2 commanders (both must have "Partner" or one must have "Partner with X")
  - Special case: Some cards explicitly state "can be your commander"
- **Deck Composition**: 99 + 1 Commander = 100 cards total
- **Singleton Rule**: Exactly 1 copy of each card, except Basic Lands
  - Basic Lands: Any quantity allowed
  - All other cards: Max 1 copy per unique card name
- **Color Identity**:
  - Color Identity = all mana symbols in mana cost + all mana symbols in card text
  - Every card in deck must have color identity that is subset of Commander's color identity
  - Example: Commander "Izzet Spell Slinger" (Blue/Red) → deck cannot contain Black mana symbols anywhere
- **Banned List**: Official banned cards cannot be in deck
  - Currently ~20 cards banned
  - Ban list updated periodically

### Game Rules (Commander-Specific)

- **Command Zone**: Each player's commander starts in Command Zone (not in hand/library)
- **Casting Commander**: Commander can be cast from Command Zone like from hand
  - Can cast any time you have priority (like Instant for first cast, then subject to timing after)
  - Casting cost increases by 2 per additional cast from Command Zone (Commander Tax)
- **Commander Damage**: Optional game rule
  - If enabled: 21 damage from a single commander = that player loses (in addition to 20 life total)
  - For MVP: Probably disabled (adds complexity)
- **Duplicate Legendary Rule**: If you control 2+ copies of same Legendary, all but one go to graveyard
  - Relevant for simulation if copied

### Implementation Implications

- **Parser**: Must recognize Commander declaration (usually "Commander: CARDNAME" at end of list)
- **Validator**: Color Identity calculation + checking
- **Deck Model**: Separate storage for Commander vs. Main Deck
- **Game Engine**: Command Zone tracking, Commander Tax tracking
- **Ban List**: External data source, must be maintained

### Commander-Specific Validation Checklist

```code
✓ Commander is legendary (or has "can be commander" text)
✓ Total cards = 100 (1 commander + 99 deck)
✓ Singleton rule: No duplicates except Basic Lands
✓ All cards in Color Identity of Commander
✓ No banned cards
✓ Partner rules correct (if applicable)
✓ All card names resolved to valid cards
```
