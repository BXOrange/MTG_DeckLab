# DeckLab — Die Projektgeschichte

## Ursprung: "Kann ich mein Deck in einer Sandbox testen?"

Magic: The Gathering ist ein Spiel mit über 30 Jahren Regeln, Sonderfällen und Mechaniken, die nicht in einem menschlichen Kopf Platz haben. Mit über 30.000 verschiedenen Karten gibt es unendlich viele Kombinationen. Die ursprüngliche Frage war simpel: **Wie teste ich ein Commander-Deck, ohne gegen echte Gegner spielen zu müssen? Wie validiere ich, dass eine Combo-Kette auch wirklich so funktioniert, wie ich sie verstanden habe?**

DeckLab begann als ein interner Sandbox-Modus — "Goldfisch" genannt, weil man sein Deck gegen einen passiven Gegner spielt, der keine Aktionen nimmt. Der Name ist aus der MTG-Community, und die Metapher ist treffend: Man sollte mindestens gegen einen Fisch gewinnen können.

## Phase 1: Grundinfrastruktur (2023–2024 früh)

Die ersten Commits zeigen die klassische Bootstrapping-Sequenz:

1. **Frontend-Layout & Deckimport** – Ein sauberes deutsches Interface zum Eingeben von Decklist-Text
2. **Card Database** – Ein lokaler SQLite-Cache mit Scryfall-Integration, um nicht ständig die API zu hammern
3. **Deck Storage** – Gespeicherte Decks persistent ablegen und abrufen
4. **Basic Game Engine** – Die ersten Gameplay-Loop-Ansätze

Die Erkenntnisse aus dieser Phase:
- **Offline-first**: Das Projekt sollte ohne Internet starten können. Der Cache sollte selbstheilend sein. Später würde das zum Zentralprinzip: `pip --no-index` für den venv, lokale Datenbank, Scryfall-Caching mit Selbstheilmechanismen.
- **Separation of Concerns**: Frontend (JavaScript, kein Build-Step, buildless ES Modules), Backend (Python FastAPI), klare API-Grenzen.
- **Decklist Parser**: Der Decklisten-Parser musste auf beide Seiten verfügbar sein (Frontend + Backend), um Redundanz zu vermeiden.

## Phase 2: Game Engine Foundation (2024 Frühjahr–Sommer)

Die echte Herausforderung begann: **Die Comprehensive Rules umsetzen.**

Das MTG-Regelwerk ist nicht nur groß, sondern auch tückisch:

- **Der Mana-Pool** — eine vollständig separate Buchführung: Hybrid-Mana, Phyrexian-Mana, Farbbeschränkungen (RULE 605), beliebige Farbkombinationen
- **Combat** — nicht nur Angriff und Blockade, sondern auch ~30 verschiedene Evasions-Keywords, Blocking-Beschränkungen, komplexe Verletzungsregeln
- **Der Stack** — nicht einfach "eine Liste von Dingen", sondern eine Zustandsmaschine mit Priority (RULE 117), Trigger-Limiter, Resolution
- **Permanente mit Zustand** — Tap/Untap, Marker, Verwandlung (DFCs), Levels

Die Durchbrüche dieser Phase:

1. **Token Handling** — Karten können während des Spiels Tokens erzeugen. Diese sind nicht echte Cards, sondern GameObject-Instanzen. Der Token-Datenbank-Ansatz (via Scryfall) wurde später zum Standard.

2. **Layer System (RULE 613)** — Dies war ein konzeptioneller Wendepunkt. Statt Effects "in beliebiger Reihenfolge" zu stapeln, werden sie in 7 numerierte Layer aufgelöst: Hier findet Addieren, Subtrahieren, Typenänderungen und Kontrolltransfers statt — in dieser exakten Reihenfolge, immer, unabhängig davon, in welcher Reihenfolge die Effects anlegen wurden. Das ist der Grund, warum die Engine überhaupt funktioniert.

3. **Effect Binding** — Ein GameEffect ist kein String, kein Baum. Es ist ein typiertes Objekt mit Parametern: `{"type": "deal_damage", "amount": 3, "recipient": "target"}`. Ein `EffectRegistry` mappt Typ-Strings auf Python-Klassen. Eine `AbilitySpec` ist reine Daten (JSON-kompatibel), die Sicherheitsgrenze zwischen Oracle-Text und ausgeführtem Code.

4. **Ability Catalogue** — Statt jede Karte zu parsen, könnte man einfach per Hand die Fähigkeiten schreiben. Dieser Ansatz wurde später zur Fallback-Strategie, wenn der Parser nicht alles konnte — aber zunächst brauchte man *irgendwelche* Karten zum Spielen.

## Phase 3: Parser Foundation (2024 Sommer–Herbst)

Der Parser ist das größte Problem bei Magic. Jede Karte hat Oracle-Text in Englisch. Dieser Text ist halb reguliert, halb Kunstprosa. Die Regeln sind konsistent (mit ~500 untergeordneten Ausnahmen), aber die Syntax ist nicht kontextfrei.

Beispiele:
- "Whenever you cast a spell, draw a card." — Vorbedingung, Effekt
- "Whenever a creature you control enters, put a +1/+1 counter on another target creature." — Vorbedingung, Scope ("you control"), Effekt mit Targeting
- "Exile the top card of your library. You may play it this turn." — Sequenz von Effects, mit optionaler Continuance

Der Parser wurde in Phasen aufgebaut:

1. **normalize**: Vereinheitliche Schreibweisen. "{T}" wird zu "Tap". "and/or" wird zu "or".
2. **segmenter**: Zerlege einen Text in Sätze und Clauses. Erkenne Trigger-Bedingungen ("Whenever..."), Kosten, Effekt-Bodies.
3. **catalogue/handlers**: Jeder Effekt-Typ hat einen Handler. "Deal X damage" mappt zu einem `DealDamageEffect`-Spec.
4. **gate.parse_oracle**: Das Haupttor. Gibt `AbilitySpec`-Listen zurück oder `UNMODELED`, wenn etwas nicht passt.

Kritische Erkenntnisse:

- **Fail-closed ist besser als halbgaren**: Ein Card wird nur dann als `MODELED` markiert, wenn *jede* Clause erkannt wurde. Das bedeutet: Viele Cards sind `UNMODELED`, aber die, die `MODELED` sind, funktionieren auch wirklich korrekt.
- **Pattern Matching ist hart**: Eine "Echse mit Power 2 oder weniger enters" ist syntaktisch ganz anders zu "eine Echse enters". Statt eine monolithe Grammatik zu schreiben, ist es klüger, atomare Teile zu haben und sie zusammenzusetzen.
- **Metriken sind kritisch**: Wie viele Cards sind `MODELED`? Nach jedem Change neu messen mit `parser_probe.py`, nicht raten.

## Phase 4: Komplexe Kartstrukturen (2024 Herbst–Winter)

Mit einem funktionsfähigen Parser und einer funktionsfähigen Engine kamen jetzt die schwierigen Karttypen:

- **Double-Faced Cards (DFCs)**: Eine Karte kann zwei Seiten haben. "Liliana, Waker of the Dead // Liliana's Mastery". Die Engine brauchte `front_face`/`back_face` Unterscheidung und Transform-Mechanik.
- **Sagas**: Eine spezielle Permanent-Kategorie mit Lore-Countern und kapitelartigen Triggers. RULE 715 hat eigene Auflösungsregeln.
- **Adventures**: Ein Spell mit zwei Seiten — man kann den Spell werfen oder ein Adventure ausspucken, das die Karte sofort ins Graveyard schickt.
- **Replacement Effects**: "If X happens, do Y instead." Diese sind **nicht** Triggered Abilities — sie ändern, was passiert, bevor das normales Effekt-Auflösungs überhaupt anfängt.

## Phase 5: Multiplayer & Sessions (2025 Frühjahr)

Nachdem der Solo-Modus (Goldfish) funktionierten, kam die große Frage: **Was ist mit echtem PvP?**

Multiplayer ist nicht nur "spiele mit mehr als 2 Spielern". Es ist eine ganz andere Kategik:

- **Lobby**: Spieler joinen einen Tisch. Nicht authentifiziert (dieses Projekt hat no User-Accounts), aber mit einem `client_token` für Browser-Session-Kontinuität.
- **Presence & Reconnects** (RULE 104.3a): Wenn ein Spieler trennt, passiert nicht sofort Gameloser. Es gibt eine 90-Sekunden-Grace-Period. In der Zeit wird Priority automatisch übergeben.
- **Priority (RULE 117)**: Das ist das echte Problem. In Solo läuft der Stack automatisch. In Multiplayer hält der Stack an, nachdem ein Spell/Ability auf den Stack geht. Der aktive Spieler hat Priority. Wenn er passa, geht Priority zum nächsten Spieler. Alle passen = Stack löst eine Karte auf. **Das ist interaktiv und muss in Echtzeit funktionieren.**
- **WebSockets**: REST ist nicht schnell genug. Eine WebSocket-Verbindung pro Spieler pro Spiel, die bidirektional Broadcasting der Board-Updates.
- **Bots**: "Solo gegen Bots" (UC5 — Use Case 5). Ein echter Multiplayer-Tisch, aber mit KI-Spielern gefüllt. Ein GoldfishBot (spielt nur Lands, passt sonst) war schnell. Ein GreedyBot (spielt alles) war schneller.

Wichtigste Entdeckung aus dieser Phase: **Die Engine braucht keine Multiplayer-Vorstellung. Sie braucht nur pro-Aktion Actor-IDs und pro-View-Request Perspective-Filter.** Der Rest ist Lobby-Buchführung.

## Phase 6: Riesige Parser-Batches & ENG-37 (2025 Sommer–Herbst)

Nachdem die Basis stabil war, kam eine lautlose Architektur-Refaktorierung: **ENG-37 — Fusion Retirement**.

Das Problem: Im Oracle-Text-Parser gab es "Fusions" — Effekt-Kombinationen, die eine neue, spezielle Klasse brauchten. "Draw a card, then discard a card" war eine Fusion. "Create a token and grant it a keyword" war eine Fusion. Mit Hunderten dieser Dinge wurde der Code bald unlesbar.

Die Erkennnis: **Statt Fusions zu schreiben, schreibe atomare Primitives und kombiniere sie mit einer Kompositions-Language.**

ENG-37 war ein 3–6 Monate großes Refactoring, das die gesamte Effect-Katalog auf `seq` (Sequenz), `if_else` (Conditionals), `optional` (You May), `for_each` (Wiederholung) und `bind` (Messwert berechnen und einsetzen) reduzierte. Keine Fusions mehr. Der Code wurde um 50% kürzer. Die Testabdeckung stieg.

**Lessons learned aus ENG-37:**
1. Kleine, testbare Einheiten gewinnen gegen monolithe "clevere" Lösungen.
2. Eine Kompositionssprache ist billiger als Hunderte spezialisierte Klassen.
3. Messungen von "wie viele Cards funktioniert jetzt" sollten vor und nach großen Refactorings passieren.

## Phase 7: Commander-fokussierter Sprint (2026 Frühjahr–heute)

Seit Frühjahr 2026 liegt der Schwerpunkt auf **Commander-Legality** und realen Commander-Decks. Das Projekt hat echte Saved Decks, und mehrere davon sind 99-Karten-Commander-Decks aus aktiver cEDH-Meta.

Entdeckungen:

1. **Komplexe Mana-Länder**: Filter-Länder wie Twilight Mire, die "Add {B}{B}, {B}{G}, or {G}{G}" produzieren, waren für die Auto-Tap-Engine unmöglich. Ein neuer `find_tap_plan` mit Converter-Simulation war nötig.

2. **Hand-Author-Card** Skill: Nicht alles kann der Parser treffen. Für echte Ein-Karten-Gaps (z.B. eine Karte, die niemand sonst hat) ist es schneller, die Fähigkeit per Hand zu schreiben. Der Skill wurde entwickelt, um diesen Prozess zu accelerieren.

3. **Coverage-Messungen sind kritisch**: Nachdem eine neue Batch Parser-Verbesserungen landet, steigt die Coverage von z.B. 44% auf 45.8%. Aber in einem 99-Karten-Deck zählt nicht die globale Coverage — es zählt, ob *dein* Deck spielbar ist. Deshalb jetzt auch Commander-spezifische Messungen.

4. **Concurrent Sessions**: Der Entwickler hat oft mehrere Claude-Instanzen auf demselben Working Directory laufen. Das heißt: Jede Edit auf shared Docs (BACKLOG.md, Done_Backend.md) brauchte Isolation. Mit `GIT_INDEX_FILE` temp-Indizes werden nur die aktuellen Changes committed.

5. **Half-Implementations sind teuer**: Wenn eine Batch beginnt und eine neue Mechanic braucht, aber dann nicht zu Ende gebracht wird, wird sie zu einer "Deferred" Ticket. Beim nächsten Mal wird die gleiche Mechanic von einer *anderen* Batch gebaut — aber die ursprüngliche Ticket wird nie gelöst. Das ist Zeitverschwendung. Die Disziplin jetzt: Entweder fertig machen oder per Hand implementieren (via `hand-author-card`) oder zu DEFERRED verschieben. Kein schönes Halbes.

## Phase 8: Aktuelle Lage (September 2026)

### Coverage-Status

- **Globale Parser Coverage**: 45.86% (15,963 / 34,811 Cards)
- **Commander-Legal Coverage**: 48.2% (15,332 / 31,830 Cards) — das ist was zählt
- **Aktive Tickets**: PAR-117 (Trigger-Condition Group Subjects), die Indefinite Long Tail (PAR-12)

### Architektur-Highlights

1. **Separation of Concerns**: 
   - Frontend (JS, no build, no state)
   - Backend (Python, FastAPI, all game logic)
   - Card Parser (isolated from game engine, fail-closed)
   - Ability Catalogue (fallback for one-offs)

2. **The Layer System**: Die RULE 613 Layer-Engine ist die Wirbelsäule. Alles, das eine Permanent-Charakteristik permanent oder ephemeral ändert, geht durch 7 Layer.

3. **Priority Architecture**: Interactive Priority (RULE 117) ist opt-in pro Session. Solo = automatisch. Multiplayer = spielergesteuert. Bots = deterministisch.

4. **Offline-Safe Startup**: Das Projekt startet ohne Internet. Keine Netzwerk-Calls außer zum Cachen neuer Kartendaten.

5. **Test/Production Isolation**: Früher wischten Tests die echte Card-Cache weg. Jetzt separate `backend/cache/test/` mit automatischem Reseed.

### Dokumentation als Code

- `CLAUDE.md`: Technisches Orientierungsdokument. Kept in sync.
- `Done_Backend.md` / `Done_Frontend.md`: Worklog (was gebaut wurde, warum), nicht chronologisch sondern per-Feature organisiert.
- `BACKLOG.md`: Nur offene Tickets. Keine History, keine "geschlossenen" Items. Kurativ gelesen.
- `PARSER_LONG_TAIL.md`: Strategie für die indefinite tail (kleine Kartenclusters, Singletons, Heuristiken).

## Kritische Lektionen

### 1. Metriken Lügen
Eine neue Parser-Regel sieht aus wie "+20 Cards". Aber wirklich zählt: Funktionieren *deine* Decks? Und funktionieren sie wirklich oder nur in Parse-Tests? Die Lösung: `parser_probe.py` (parse-Verdikt) UND `engine_bench.py` (execute-Test mit echtem GameEngine).

### 2. Half-Implementations sind teuer
Ein Primitive "deferred" bedeutet nicht "wir machen das später." Es bedeutet "wir heben die Schulden auf." Diese Schuld wird dann 4 Monate später von einer anderen Batch wieder entdeckt und wieder aufgeschoben. Die Disziplin: Wenn du es anfängst, mach es zu Ende oder tu es per Hand.

### 3. Fail-Closed ist besser als halb-funktionierend
Ein Card der `UNMODELED` ist, funktioniert nicht. Ein Card der `MODELED` ist mit Garantie, funktioniert richtig. Das ist das Gegenteil von vielen anderen Projekten, wo "halb funktionieren" Norm ist.

### 4. Decompose, nicht Fuse
ENG-37 lehrte: Statt Hunderte spezialisierte `XYZ_Effect`-Klassen, lieber 5 Kompositions-Primitive und Kombinatorik. Der Code wird länger (mehr Verschachtelung), aber lesbarer und wartbarer.

### 5. Isolation ist kritisch
Mehrere Sessions auf dem selben Working Directory = jeder braucht seinen eigenen Test-Cache, eigenen Config-State. Die Lösung war nicht elegant, aber sie funktioniert: `MTG_CACHE_DIR` env-var + temporary `GIT_INDEX_FILE`.

### 6. Der Parser ist unfertig und wird es immer sein
Mit 30.000 Cards gibt es immer eine Karte, die ihre eigene Syntax hat. Das akzeptieren und eine Escape-Valve (hand-author-card) haben ist billiger als versuchen, alle möglichen Spielarten zu parsen.

## Wo DeckLab heute Steht

DeckLab ist kein Spike wie hearthstone-online oder Magic Arena. Es ist eine **Rules-Accurate Game Engine für dich selbst**, gebaut in der Überzeugung, dass echte Regel-Treue wichtiger ist als 99% Coverage.

Das Projekt hat:

- ✅ Eine vollständig implementierte RULE 613 Layer Engine
- ✅ Interactive Priority (RULE 117) für Multiplayer
- ✅ Bots und Solo-gegen-Bots Gameplay
- ✅ Replay/Puzzle Mode
- ✅ 45%+ Oracle-Text Parser Coverage (mit Zero Regressions)
- ✅ Deutsches Interface
- ✅ Offline-Safe Startup
- ✅ Concurrent-Session Discipline

Was nicht implementiert ist:
- ❌ User Accounts (Authentifizierung)
- ❌ Elo / Matchmaking
- ❌ Streaming / Spectate
- ❌ Visuelle 3D-Cards
- ❌ Sticker (absichtlich non-goal)
- ❌ Noch ~50 Kartenclusters, die ihre eigene Parser-Grammatik brauchen

Das Projekt ist nicht "fertig". Es wird es nie sein — Magic ist eine Living Game, und jedes neue Set bringt neue Mechaniken. Aber es ist **stabil**. Die Engine funktioniert. Reale Decks spielen zu Ende. Neue Batch bringen immer +N mehr Cards und 0 Regressions.

## Für die Zukunft

Der nächste große Fokus: **Die lange Tail**. 15.000 unmodelierte Cards sind viele. Aber wenn nur 100 davon sind in deinen Decks, ist die Zahl irrelevant. Der Schwerpunkt sollte auf Deck-Coverage sein, nicht auf Cache-Coverage.

Tools dafür existieren schon: `scripts/commander_tail_report.py`, `scripts/deck_coverage.py`. Die Idee ist, die Commander-Legalen Cards nach "welche sind in echten Decks" zu sortieren und dort anzufangen.

Eine andere Idee: Mehr Automatisierung des Hand-Authoring. Der `hand-author-card` Skill macht es einfacher, aber ein nächster Schritt wäre noch mehr Boilerplate-Reduktion.

---

**TL;DR**: DeckLab war eine Reise von "Ich will ein Deck testen" zu "Ich habe eine vollständige MTG Rules Engine gebaut". Unterwegs gab es Umwege (ENG-37), Fehlschläge (Parser Coverage ist schwer), und überraschende Erkenntnisse (Fail-Closed ist Gold, Half-Implementations sind teuer). Heute funktioniert es. Nicht perfekt, aber richtig.
