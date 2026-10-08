# DeckLab: MVP Use Cases (Revised)

> **Status (2026-10):** This document began as a proposed MVP, not as a
> description of the current product. Its original CLI/LLM assumptions and
> week-based phases are obsolete. The use cases and R6 UI requirements below
> are aligned with the implemented web app; R1–R4 remain useful domain
> references and are cited by code, but are not an exhaustive statement of
> current engine coverage. For shipped frontend behavior, see
> [`../concepts/05_GAME_UI_AND_CARD_INTERACTION.md`](../concepts/05_GAME_UI_AND_CARD_INTERACTION.md),
> [`../concepts/04_SERVER_CLIENT_ARCHITECTURE.md`](../concepts/04_SERVER_CLIENT_ARCHITECTURE.md),
> and [`../implementation-state/Done_Frontend.md`](../implementation-state/Done_Frontend.md).
> For current open work and implementation status, see
> [`../implementation-state/BACKLOG.md`](../implementation-state/BACKLOG.md)
> and [`../implementation-state/10_COMPLETION_ROADMAP.md`](../implementation-state/10_COMPLETION_ROADMAP.md).

---

# PRODUCT SCOPE

DeckLab ist inzwischen eine **browserbasierte Deck-Verwaltung, Analyse und
Spieloberfläche** mit einer serverseitig maßgeblichen Regel-Engine. Das
Frontend ist eine statische, buildlose ES-Module-App; eine CLI-Spieloberfläche
und eine LLM-Integration gehören nicht zum implementierten Produkt.

Die nachfolgenden Use Cases beschreiben den heutigen Umfang. Wo ein
Analysebereich noch nicht umgesetzt ist oder eine Anforderung aus dem alten
MVP stammt, ist das ausdrücklich markiert.

---

# PROJECT GOALS

## Deck building tool

**Status:** Neues, geplantes Feature; Umsetzung siehe
[VIS-15 im Backlog](../implementation-state/BACKLOG.md#vis--visuals).

DeckLab soll einen eigenen Bereich **„Deck building tool“** erhalten, in dem
Benutzer Commander-Decks von Grund auf zusammenstellen oder bestehende Decks
gezielt bearbeiten können. Der Bereich verbindet Kartenauswahl, Deckbearbeitung
und Analyse zu einem durchgängigen Deckbau-Workflow.

### Geplanter Funktionsumfang

- Ein neues Deck beginnen oder ein gespeichertes Deck zur Bearbeitung laden.
- Commander auswählen und Karten über Suche und Filter in der vorhandenen
  Kartendatenbank finden; Kartendetails vor der Auswahl anzeigen.
- Karten hinzufügen, entfernen und Mengen ändern; Deckgröße, Mana-Kurve und
  Farbverteilung während der Bearbeitung anzeigen.
- Unvollständige Decks als Entwürfe bearbeiten und speichern; Legalitätsprobleme
  sichtbar machen und die vorhandene serverseitige Validierung wiederverwenden.
- Das fertige Deck als neues Deck speichern oder das geladene Deck bewusst
  aktualisieren und anschließend für Analyse und Spielmodi verwenden.

### Abnahmekriterien

Der neue Bereich ist über die Hauptnavigation erreichbar. Benutzer können ein
Deck ohne eingefügte Deckliste aufbauen, einen Entwurf speichern und erneut
öffnen sowie ein bestehendes Deck bearbeiten, ohne es versehentlich zu
überschreiben. Änderungen werden in den Deckkennzahlen und der
Legalitätsrückmeldung abgebildet; ein vollständiges, legales gespeichertes Deck
ist in den vorhandenen Analyse- und Spielabläufen verfügbar.

---

# PART 1: REVISED USE CASES

## USE CASE 1: Deckliste Laden & Validieren

### Description
Benutzer fügt eine Commander-Deckliste ein oder importiert sie und erhält
sofortiges Parse-Feedback sowie anschließend die maßgebliche serverseitige
Kartenauflösung und Legalitätsprüfung.

### Actor
Benutzer im Browser (Deck editieren / externer Deckimport)

### Preconditions
- Deckliste liegt als Text oder unterstützter externer Import vor
- Kartendatenbank verfügbar

### Main Flow
1. Benutzer fügt eine Liste in Commander-, Mainboard- und Sideboard-Felder
   ein oder lädt sie über einen unterstützten Importpfad.
2. Das Frontend parst die Liste lokal für sofortiges Feedback.
3. Der Server löst Kartennamen auf und prüft die Deckstruktur sowie
   Commander-Legalität:
   - Legendary Commander
   - Singleton Format (max 1 Kopie außer Basic Lands)
   - 100 Karten Total
   - Color Identity Constraint
   - Ban List
   - Partner Rules (falls vorhanden)
4. Das Frontend zeigt Parsefehler, nicht aufgelöste Karten und konkrete
   Legalitätsgründe getrennt an.
5. Benutzer kann das Deck als neues Deck speichern oder ein geladenes Deck
   aktualisieren und es anschließend verwalten, analysieren oder im
   Goldfisch-Modus verwenden.

### Postconditions
- Deckliste ist geladen und validiert
- Legal-Status ist bekannt
- Alle Kartinformationen sind verfügbar
- Bei Fehlern: Klare Fehlermeldung mit Korrektur-Vorschlag

### Requirements (Architektur)
- **Parser**: Unterstützte Decklisten- und Importformate
- **Validator**: Commander-Regeln (Legendary, Singleton, Color Identity, Ban List, Partner)
- **Card DB**: Vollständige Kartinformationen + Legality Tracking
- **Error Handling**: Aussagekräftig, mit Suggestions

---

## USE CASE 2: Gespeichertes Deck analysieren

### Description
Benutzer öffnet die Analyse eines gespeicherten Decks. Die statische Analyse
berechnet Kennzahlen und Deckzusammensetzung; die Bracket-Analyse zeigt eine
inoffizielle Heuristik. Eine dynamische Strategie-/Synergieanalyse ist
derzeit nicht implementiert.

### Actor
Benutzer im Browser; statische und Bracket-Auswertung laufen lokal im Frontend

### Preconditions
- Gespeichertes Deck und aufgelöste Kartendaten verfügbar

### Main Flow
1. Benutzer öffnet **Deck analysieren** aus der Deckverwaltung.
2. Die statische Analyse zeigt unter anderem Manakurve, Land- und
   Typverteilung, Manaquellen, Starthand-/Landwahrscheinlichkeiten und
   erkannte funktionale Kategorien.
3. Die Bracket-Analyse zeigt eine heuristische Mindest-Bracket-Schätzung,
   ihre Signale und die zugrunde liegenden Karten.
4. Der Bereich **Dynamische Analyse** weist darauf hin, dass Strategie,
   Archetyp, Synergien und Gesamtkohärenz noch nicht implementiert sind.

### Postconditions
- Die vorhandenen Kennzahlen und Heuristiken sind sichtbar.
- Die Oberfläche stellt heuristische Ergebnisse nicht als offizielle
  Bewertung oder vollständige Strategieanalyse dar.
- Für die nicht implementierte dynamische Analyse wird kein Ergebnis
  vorgetäuscht.

### Requirements (Architektur)
- **Statische Analyse:** Kennzahlen nachvollziehbar aus den verfügbaren
  Deck- und Kartendaten berechnen.
- **Bracket-Analyse:** Als inoffizielle Heuristik kennzeichnen und ihre
  erkannten Signale samt Karten zeigen.
- **Statusanzeige:** Nicht implementierte Analysen eindeutig als solche
  darstellen; keine LLM-Abhängigkeit voraussetzen.

---

## USE CASE 3: Goldfisch-Modus (Solo-Spiel)

### Description
Benutzer spielt ein gespeichertes Deck solo gegen einen passiven Dummy mit
der echten Backend-Regel-Engine. Replay/Puzzle ergänzt diesen Ablauf um einen
frei erstellbaren oder importierten Spielzustand.

### Actor
Benutzer im Browser

### Preconditions
- Ein gespeichertes, serverseitig legales Deck für Goldfisch; Replay kann
  ohne gespeichertes Deck mit einem beliebigen Boardzustand gestartet werden.

### Main Flow
1. Benutzer wählt ein legales gespeichertes Deck; das Spiel wird gestartet
   und eine Starthand samt Mulligan-Aktionen angezeigt.
2. Nach dem Behalten steuert der Benutzer das Spielbrett. Die Engine liefert
   erlaubte Aktionen; der Benutzer spielt Länder, wirkt Zauber, aktiviert
   Fähigkeiten, wählt Ziele und führt Kampfaktionen aus.
3. Die Session verarbeitet Aktionen, Stack und Engine-Entscheidungen; die
   Oberfläche zeigt den aktualisierten Zustand und gegebenenfalls
   Ziel-/Entscheidungsdialoge.
4. Solo-Steuerung erlaubt unter anderem Schrittfortschritt,
   Zurücknehmen/Neustart und Spielauswertung.
5. Benutzer kann die aktuelle Position als Replay exportieren.
6. Im Replay/Puzzle-Modus kann er ein Board frei bearbeiten, importieren oder
   exportieren und anschließend in denselben interaktiven Spielmodus wechseln.

### Postconditions
- Benutzer hat eine komplette Goldfisch-Runde gespielt
- Alle Züge sind nach echten Regeln aufgelöst worden
- Der aktuelle Spielzustand oder die Spielauswertung ist sichtbar.
- Eine exportierte Replay-Datei kann im Replay/Puzzle-Modus weiterverwendet werden.

### UI/UX Implications
- Spielzustand, Zug/Phase/Schritt, Zonen und offene Stack-Objekte lesbar
  darstellen.
- Vom Server gelieferte legale Aktionen unmittelbar an den betroffenen
  Karten anbieten; gesperrte Aktionen mit Grund kenntlich machen.
- Mulligans, Ziele, Kostenwahlen und ausstehende Engine-Entscheidungen
  verständlich und abbrechbar bedienen lassen, wo die Spielregeln es zulassen.
- Goldfisch- und Replay-Steuerung als Solo-Funktionen kennzeichnen.

### Requirements (Architektur)
- **Full Game Engine**: Alle MTG Regeln implementiert
- **Game State Display**: Browser-UI
- **Input Validation**: Nur legale Moves erlaubt
- **Stack Resolution**: Korrekt nach RULE 608
- **Mulligan Logic**: Benutzer wählt Keep/Mulligan
- **Fehlerfeedback**: Serverablehnungen und Sperrgründe verständlich anzeigen

---

## USE CASE 4: Multiplayer-Modus

### Description
Zwei bis vier Personen spielen an einem gemeinsamen Tisch gegen dieselbe
Regel-Engine. Freie Plätze können mit Bots besetzt werden; ein laufendes
Spiel kann auch beobachtet werden.

### Actor
Host, zwei bis vier menschliche Spieler und optional Bots oder Zuschauer

### Preconditions
- Alle menschlichen Spieler verbinden sich mit demselben Backend.
- Jeder Spielersitz hat ein legales gespeichertes Deck; ein Bot-Sitz wird
  vom Host verwaltet.

### Main Flow
1. Spieler öffnen Multiplayer-Setup; ein Host erstellt einen Tisch mit zwei
   bis vier Plätzen, weitere Spieler treten bei.
2. Host konfiguriert die Tischoptionen. Alle Sitze wählen ein legales Deck
   und bestätigen ihre Bereitschaft; der Host kann freie Sitze mit Bots
   besetzen.
3. Host startet, sobald alle Plätze besetzt und bereit sind. Jeder
   menschliche Spieler entscheidet auf seinem eigenen Client über
   Behalten oder Mulligan.
4. Das gemeinsame Spiel läuft mit echter Priorität. Spielaktionen werden
   dem handelnden Sitz zugeordnet und serverseitig validiert.
5. Das Backend sendet jedem Spielersitz eine eigene, um verdeckte
   Informationen bereinigte Ansicht. Die Oberfläche aktualisiert das Board
   über den Lobby-WebSocket.
6. Bots handeln über ihre eigene bereinigte Ansicht und ausschließlich
   anhand ihrer eigenen legalen Aktionen.
7. Spieler können zuschauen, sich wiederverbinden oder – abhängig von der
   Tischkonfiguration – einen eigenen letzten Zug zurücknehmen.

### Postconditions
- Der gemeinsame Spielzustand wird für die jeweiligen Perspektiven angezeigt.
- Ein beendetes Spiel zeigt den Endzustand und das Ergebnis.
- Verdeckte Informationen bleiben anderen Spielern und Zuschauern verborgen.

### Interaction Model
- Turn-basiert (nicht real-time)
- Priorität und handelnder Sitz werden serverseitig verwaltet.
- Kein "Zug weiter"-Button: alle Spieler geben Priorität weiter; der Stack
  löst sich auf oder der Schritt endet nach den Regeln.
- Nur die eigene Hand wird übertragen; fremde verdeckte Karten bleiben
  serverseitig verborgen.
- Wiederverbindung und zeitgesteuertes Auto-Passen unterstützen den
  Spielfluss.

### Requirements (Architektur)
- **Full Game Engine**: Multiplayer-States, Priority System
- **Priority Tracking**: Wer hat Priority? Wer kann reagieren?
- **Verbindung und Präsenz**: gemeinsame Tische und Wiederverbindung
- **UI**: Beide Spieler sehen relevante Informationen (nicht Gegners Hand!)

---

## USE CASE 5: Spiele mit Bots

### Description
Goldfisch- und gierige Bots besetzen Sitze im Multiplayer oder spielen
gegen einen einzelnen Benutzer im Modus **Solo gegen Bots**. Bots sind
Spieler am selben Engine-Interface, keine separate Regelausführung.

### Actor
Benutzer beziehungsweise Host und Bot-Spieler

### Preconditions
- Benutzer startet Solo gegen Bots oder der Host fügt einem vorbereiteten
  Multiplayer-Tisch einen Bot hinzu.

### Main Flow
1. Benutzer beziehungsweise Host wählt Bot-Typ und Deck.
2. Bot liest nur seine eigene Session-Ansicht und die darin angebotenen
   legalen Aktionen.
3. **Goldfisch-Bot** spielt Länder und passt sonst; **Gieriger Bot**
   wählt sofort verfügbare Aktionen und einfache Erstziele.
4. Die Engine validiert alle Bot-Aktionen wie Aktionen menschlicher Spieler.
5. Ergebnisse erscheinen auf dem gemeinsamen oder Solo-Spielbrett.

### Bot-Verhalten und Grenzen
Die vorhandenen Policies sind einfache Spieltests und keine
strategischen Deck-Piloten. Sie erhalten keine direkten Engine- oder
verdeckten Gegnerdaten; Lookahead, Monte-Carlo-Auswertung und
Threat-Assessment sind nicht implementiert.

### Postconditions
- Bot-Aktionen werden durch dieselbe Regel-Engine geprüft wie
  menschliche Aktionen.
- Bot-Züge werden zusammen mit den resultierenden Ansichten angezeigt.

### Requirements (Architektur)
- **Bot-Richtlinien**: Entscheidungen ausschließlich auf eigener View und
  legal actions basieren
- **Policies**: Goldfisch- und gierige Policy für aktuelle Spielmodi

---

# PART 2: ARCHITECTURE IMPACT

Die Anforderungen werden heute als Browser-App umgesetzt. Die statische
Deckanalyse und die Bracket-Heuristik sind vorhanden; dynamische
Deckstrategieanalyse und LLM-gestützte Auswertung sind kein implementierter
Bestandteil. Goldfisch, Replay/Puzzle, Multiplayer und Solo gegen Bots
verwenden die gemeinsame serverseitige Spiel-Engine.

### Architecture Layers (Revised)

```
Layer 5: UI/Game Interface
         (statische Browser-App)
         
Layer 4: Game Engine (Core)
         Turn Loop, Phase Loop, Priority, Stack, State
         
Layer 3: Rules Engine
         RULE 601/602/603/608/607/504 + Commander-Specific
         
Layer 2: Card Services
         Card Effect Implementation
         
Layer 1: Data Layer
         Card DB, Deck Storage, Game State
```

Deckanalyse ist ein eigener Produktbereich: statische Kennzahlen und
heuristische Bracket-Auswertung laufen im Frontend; die dynamische
Strategieanalyse ist laut aktuellem Produktstand noch nicht implementiert.

---

## Architektur-Leitplanken des aktuellen Produkts

- Die Backend-Engine ist für Regeln, erlaubte Aktionen und den maßgeblichen
  Spielzustand zuständig; das Frontend stellt diese Informationen dar und
  übermittelt Benutzeraktionen.
- Die Spielmodi teilen Engine und Spielbrett, unterscheiden sich aber in
  Transport und verfügbaren Steuerungen.
- Multiplayer ist ein gemeinsamer, serverautoritativ verwalteter Tisch mit
  Priorität und pro Sitz redigierten Ansichten; es ist keine lokale
  Zwei-Spieler-Ansicht.
- Die Analyse darf nicht als LLM-gestützt beschrieben werden: implementiert
  sind statische Auswertungen und Heuristiken.

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
- Give clear feedback for rejected or unavailable actions
- Provide mode-appropriate undo/take-back behavior

---

## Requirement Category 5: LLM Integration (not implemented)

The requirements in this category describe an earlier proposal only. The
current application has no LLM integration; deck analysis is static or
heuristic-based. Do not treat R5.1–R5.3 as implemented or as current MVP
requirements.

### R5.1: LLM API Integration (historical proposal)
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

## Requirement Category 6: Browser UI (current product)

These requirements describe the implemented web application and are derived
from the current frontend interaction model. The client presents and submits
actions; game legality, hidden-information access and authoritative state
remain server responsibilities.

### R6.1: Navigation and mode entry
- Provide browser navigation for deck editing/import, saved decks, analysis,
  Goldfish, Solo gegen Bots, Replay/Puzzle, Multiplayer, card cache,
  engine status, settings and profile.
- Keep connection settings (server address) separate from player/profile
  preferences.
- Clearly indicate connection/loading states and distinguish failures from
  valid empty results; provide a retry path where applicable.

### R6.2: Deck editing, management and analysis
- Accept supported pasted/imported decklists and provide prompt local parse
  feedback followed by server-authoritative card resolution and legality.
- Show parse errors, unresolved cards and legality reasons distinctly.
- Support saving as a new deck or updating a loaded deck without accidental
  overwrite.
- Display saved-deck legality/coverage state and available edit, analyze,
  play and delete actions.
- Present static analysis and bracket heuristics with their limitations;
  identify the dynamic analysis as not implemented until it exists.

### R6.3: Shared interactive game board
- Present each player's zones, life, mana, turn/phase/step and stack in a
  readable, navigable layout; support the project's compact/layout
  preferences.
- Render exactly the actions supplied by the current server view. Do not
  infer or authorize game actions client-side.
- Show locked actions with the server-provided reason and surface failed
  requests as visible feedback rather than silently ignoring them.
- Provide appropriate interactions for legal actions, targets, cost choices,
  pending choices, combat assignments and mulligans.
- Reuse the shared board across Goldfisch, Replay/Puzzle, Solo gegen Bots
  and Multiplayer while exposing only controls valid for the current mode.

---

### R6.4: Multiplayer information and synchronization
- Show each player only information present in that player's server-provided
  perspective; never reveal hidden cards through client-side rendering or
  debug controls.
- Reflect priority, the acting player, connection/presence and pending
  decisions in the shared board.
- Update all clients from server-pushed views and support reconnection
  without discarding valid in-progress UI selections.
- Keep spectator views redacted and disable unilateral solo controls in a
  shared game.

### R6.5: Card presentation, localization and preferences
- Present card imagery/details consistently in deck, cache and game views;
  use cached/backend-served assets rather than direct third-party image
  requests from the browser.
- Localize user-facing UI text and keep MTG keyword names in English.
- Persist client-only preferences locally; do not imply account-backed
  identity or settings.

### R6.6: Accessibility and interaction semantics
- Provide useful alternative text for card images and semantic dialog/
  expanded-state attributes where implemented.
- Do not claim comprehensive keyboard-only, screen-reader, high-contrast or
  font-size support until those capabilities are implemented and verified.

# PART 4: NICHT IMPLEMENTIERTE ODER HISTORISCHE VORSCHLÄGE

Die folgenden Punkte stammen aus früheren MVP-Entwürfen und dürfen nicht
als vorhandene Funktion oder aktuelle Zusage gelesen werden:

- LLM-gestützte Deckanalyse und externe LLM-API
- CLI-Spieloberfläche
- Strategische Bot-KI mit Lookahead, Monte-Carlo-Auswertung oder
  Threat-Assessment
- Die in R5 genannten Prompt-, Output-Parsing- und LLM-Cache-Anforderungen

Die Oberfläche kennzeichnet die dynamische Deckstrategieanalyse derzeit
als nicht implementiert. Für tatsächlich offene Arbeit ist der
[BACKLOG](../implementation-state/BACKLOG.md) maßgeblich.

---

# PART 5: IMPLEMENTIERUNGSSTATUS

Die ursprünglich geplanten, linearen MVP-Phasen und Wochenangaben sind
historisch und bilden den aktuellen Entwicklungsablauf nicht ab. Parser,
Engine, Frontend und Multiplayer entwickeln sich ticketweise und teilweise
parallel. Maßgeblich sind die
[Completion Roadmap](../implementation-state/10_COMPLETION_ROADMAP.md),
der [Backlog](../implementation-state/BACKLOG.md) und die thematisch
geordneten [`Done_*`-Kataloge](../implementation-state/).

---

# CONCLUSION

Das aktuelle Produkt verbindet Commander-Deckimport und -verwaltung,
statische/heuristische Deckanalyse und mehrere browserbasierte Spielmodi
mit einer gemeinsamen, serverseitig maßgeblichen Regel-Engine. Die UI muss
den Spielzustand und die vom Server erlaubten Interaktionen verständlich
vermitteln, ohne selbst Regeln oder verborgene Informationen abzuleiten.
Erweiterungs- und Fertigstellungsstatus ergeben sich aus der Roadmap und
den offenen Tickets, nicht aus den historischen MVP-Phasen dieses Dokuments.
