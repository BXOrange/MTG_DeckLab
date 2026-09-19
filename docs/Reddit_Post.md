# Ich wollte nur schnell testen ob mein MTG Deck funktioniert – das ist passiert

**TL;DR:** "Ich baue einen kleinen Sandbox-Modus zum Decks testen" wurde in 2.5 Monaten eine vollständige Magic Rules Engine mit Multiplayer, Puzzle-Mode, Deckanalyse, 45% Parser Coverage und Zero Regressions. Send help (oder sag mir dass ich nicht allein bin).

---

## Das Anfang (Juli 2026)

Ich wollte einfach nur ein Tool bauen, um mein Commander Deck zu testen ohne gegen Leute zu spielen. "Ein Sandbox Modus, der spielt gegen einen passiven Gegner. Fertig." Goldfish Mode. Schnell. Einfach.

Erste Woche: Decklist Parser, Card Database, ein paar Buttons. Ich dachte mir: "Cool, in zwei Wochen bin ich fertig." 🤡

---

## Und dann kam die Rules Engine

"Warte... der Mana Pool ist komplexer als gedacht. Und Combat hat 30 Keywords. Und... RULE 613?" 

Nope. RULE 613 ist die Comprehensive Rules' Version von "hier wird's wild": sieben verschiedene Layer in einer exakten Reihenfolge, wo alle permanenten Modifikationen aufgelöst werden. Die Engine brauchte das. Punkt.

Mitte Juli: Ich schreibe Layer System. 7 Layer. Correct order. Timestamp handling. 

"Warum mache ich das überhaupt allein" war circa Commit #50.

---

## Die Parser Saga

August: "Ich baue einen Parser für Oracle Text. Wie schwer kann das sein?"

Oracle Text ist:
- Halb reguliert
- Halb Kunstprosa
- Syntaktisch nicht kontextfrei
- "Whenever a creature with power 2 or less enters and blah blah blah" ist völlig anders zu "a creature enters, put a counter"

Ich hab gegoogelt was "fail-closed design" bedeutet: "Nur MODELED markieren wenn jede Clause erkannt ist." Das war smart. Heißt zwar: viele Cards sind UNMODELED. Aber dafür arbeiten die MODELED Cards garantiert.

---

## "Kurz Multiplayer hinzufügen"

Sommer August/September: "Kurz noch Multiplayer, dann bin ich fertig."

Multiplayer ist nicht "mehr als 2 Spieler".

Multiplayer ist:
- Lobby-Management
- WebSockets (REST zu langsam für real-time Priority passing)
- RULE 117 interactive Priority (der Stack pausiert, Player passen reihum, erst wenn alle gepasst haben löst sich eine Karte auf)
- Grace periods für Disconnects
- Bots die gegen echte Players spielen (und dabei die Engine als Test fungieren)

Ich brauchte keine "Multiplayer Engine". Ich brauchte nur: Actor IDs pro Action, Perspective Filtering pro View. Der Rest ist Lobbybuchführung. "Warum habe ich das nicht einfach so designt" – glaub ich, Commit #200.

---

## The "Kurz" Momente

**Kurz noch Replay/Puzzle Mode:** "Warte, ich will eine spezifische Boardstate testen ohne 4 Turns zu spielen." → Komplette Board-Edit-API. JSON Save/Load. Man kann jede Permanent tappen, Counters setzen, Lebenspunkte ändern, alles.

**Kurz noch Deckanalyse:** "Okay aber macht mein Deck auch *wirklich* das was es soll?" → Simulated games. ProcessPoolExecutor Parallelization. Opening-Hand-Quality Metriken. "Mein Deck hat 40% Lands!" bedeutet nichts wenn es sie nie zieht.

**Kurz noch ENG-37:** "Wait, warum habe ich Hunderte spezialisierte Effect-Klassen?" → 6-Wochen Refactoring. Alles auf 5 Kompositions-Primitive (`seq`, `if_else`, `optional`, `for_each`, `bind`). Code wurde um 50% kürzer. War parallel zum Rest.

---

## Was ist jetzt da

- ✅ Vollständige RULE 613 Layer Engine
- ✅ Interactive Priority Multiplayer (real-time, WebSocket)
- ✅ Replay/Puzzle Mode (complete board editor)
- ✅ Deck Analysis (static + simulated)
- ✅ 45.86% Oracle Parser Coverage (~15.900 Cards MODELED, Zero Regressions)
- ✅ Deutsche UI
- ✅ Offline-Safe Startup (startet ohne Internet)
- ✅ Bots & Multiplayer
- ❌ Irgendwann muss mal jemand "fertig" sagen

---

## Die wichtigsten Lektionen

1. **Metriken lügen**: "+20 Cards parsed" bedeutet nichts wenn sie in echten Games nicht funktionieren. Jetzt: Parse-Test + Execute-Test mit echtem Engine.

2. **Half-Implementations sind teuer**: Ein Feature "deferred" wird 4 Monate später von einer anderen Batch wieder gebaut, weil die Original-Batch nie zu Ende kam. Neue Disziplin: Finish it, hand-author it, or defer it to DEFERRED. Keine schönen Halben.

3. **Fail-Closed ist Gold**: Ein Card der UNMODELED ist, funktioniert nicht. Ein Card der MODELED ist, funktioniert *garantiert* richtig. Das Gegenteil von "mostly works".

4. **Decompose, nicht Fuse**: ENG-37 lehrte mir: Lieber 5 Kompositions-Primitives + Kombinatorik als 100 spezialisierte Klassen. Code wird länger, aber wartbar.

5. **Concurrent Sessions sind wild**: Wenn mehrere Claude Instanzen auf dem gleichen Working Dir laufen, brauchst du Isolation. `MTG_CACHE_DIR` env var + temp `GIT_INDEX_FILE`. Hässlich aber funktioniert.

---

## Status September 2026

Das Projekt ist nicht "fertig". Magic ist eine Living Game, jedes Set bringt neue Mechaniken. Aber es ist **stabil**. Real decks spielen zu Ende. Neue Batches bringen immer +N Cards und 0 Regressions.

45% Coverage klingt nach "nicht viel". Aber: 
- **Global**: 45.86% (15.963 / 34.811)
- **Commander-Legal** (was zählt): 48.2% (15.332 / 31.830)

Für ein Side-Project vom "Ich will testen" Gedanken aus im Sommer 2026? Nicht schlecht.

---

Hat jemand das auch schon gemacht – "Kurz ein Feature" wird zur kompletten Engine? Oder bin ich der einzige der sich in die Rules Engine verliebt hat und jetzt nicht rauskann? 😅

Repo ist offen, Docs exist, insbesondere [die Projektgeschichte](https://claude.ai/artifact/GNFYSUk5zdFB9Hi2AXKE91) falls jemand die full saga lesen will.

