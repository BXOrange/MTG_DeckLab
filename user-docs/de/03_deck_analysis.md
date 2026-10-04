# 3. Deck-Analyse

Die Analyse eines Decks öffnest du über **Decks verwalten** →
**Deck analysieren** in der jeweiligen Deck-Zeile. Der Tab zeigt drei
Unter-Tabs: **Statische Analyse**, **Dynamische Analyse** und
**Bracket-Analyse**.

Alles außer dem Combo-Abgleich wird **lokal im Browser** aus den
Kartendaten des Decks berechnet — es gibt keinen KI-/LLM-Aufruf. Die
Combo-Liste gleicht das Backend mit einem lokalen Commander-Spellbook-
Snapshot ab, der bei der ersten Combo-Analyse lazy geladen und in
SQLite gespeichert wird. Die Einordnungen (Manarock, Fetchland, Board
Wipe usw.) sind
Muster-Erkennung über den Regeltext jeder Karte, keine offizielle oder
geprüfte Kategorisierung — bei ungewöhnlich formulierten Karten kann
eine Einordnung gelegentlich falsch sein oder fehlen.

## Statische Analyse

Eine rein numerische Auswertung mit einem Inhaltsverzeichnis zum
direkten Springen. Sie bewertet **nicht** Kartenqualität, Synergien
oder Archetyp — dafür ist "Dynamische Analyse" gedacht (siehe unten).

- **Übersichtskacheln**: Anzahl Tutoren, Anzahl Länder (und Anteil am
  Deck), durchschnittlicher Manawert mit/ohne Länder, Gesamt-Manawert
  und die Anzahl erkannter "Beschleuniger" (Manarocks + -dorks +
  Land-Ramp).
- **Manakurve**: ein Balkendiagramm plus Tabelle der Nichtland-Karten
  nach Manawert.
- **Erwartete verfügbare Mana pro Zug**: ein Liniendiagramm, das
  schätzt, wie viel Mana dir in welchem Zug zur Verfügung steht,
  basierend auf der exakten erwarteten Anzahl gespielter Landdrops aus
  Starthand und Zügen; Fetchlands werden beim Ausspielen geöffnet und
  finden ein Land, falls noch eines in der Bibliothek ist. Drei Linien
  werden gezeigt: nur Länder,
  Länder + Beschleuniger   ("realistisch" — Mittelwert aus 8.192 reproduzierbar
  gemischten Starthänden und Ziehungen) und Länder + Beschleuniger
  ("maximal" — günstige Ziehungen und Spielbarkeit). Manarocks können
  im Ausspielzug benutzt werden; Aktivierungskosten (z. B. bei Signets)
  werden von ihrem Ertrag abgezogen. Erkannte Länder wie Ancient Tomb
  tragen ihre tatsächliche Mana-Produktion bei. Manadorks produzieren
  erst ab dem Folgezug. Die Maximal-Kurve begrenzt Beschleuniger auf
  die nach Landdrops noch verfügbaren Handkarten. Eine vereinfachte Schätzung, keine volle
  Simulation; Mana wird als Erwartungswert berechnet, nicht als
  Wahrscheinlichkeit, die Kosten einer konkreten Karte bezahlen zu können.
- **Kartentyp-Verteilung**: Anzahl nach Typ (Kreatur, Land, Artefakt,
  Spontanzauber usw. — eine Karte mit zwei Typen zählt in beiden
  Balken).
- **Land-Archetypen**: Länder werden bekannten Zyklen zugeordnet —
  Basisland, Fetchland, Schockland, Painland, Checkland, Fastland,
  Slowland, Kampfland, Triome, Bounce-Land (Karoo), Horizon-/
  Canopy-Land, Kreaturland, MDFC (modale Zauber//Land-Karten),
  Utility-Land oder eine nicht erkannte Sammelkategorie.
- **Manasymbole: Kartenbedarf vs. Manaquellen**: pro Farbe, wie viele
  farbige Manasymbole deine Karten benötigen im Vergleich zu wie
  vielen Quellen (Länder, Rocks, Dorks), die diese Farbe erzeugen
  können.
- **Starthand & Landziehungen**: die hypergeometrische Wahrscheinlichkeit,
  genau *k* Länder in der Starthand (7 Karten) zu ziehen, plus eine
  Tabelle der erwarteten Länder im Zeitverlauf (unter Berücksichtigung
  des zusätzlichen Landes, das ein Fetchland effektiv findet).
- **Erkannte Beschleuniger**: die tatsächlichen Kartenlisten hinter
  den obigen Ramp-Zahlen — Manarocks, Manadorks, land-verzaubernde
  Auren, Land-Tutor-Ramp-Zauber, sowie Rituale und
  Treasure-Generatoren zur reinen Übersicht (letztere beide zählen
  nicht zu den dauerhaften Mana-Summen, da ein Ritual ein einmaliger
  Schub ist und ein Treasure-Token beim Nutzen verbraucht wird).
- **Funktionale Kategorien**: jede Nichtland-Karte wird genau einer
  Command-Zone-artigen Kategorie zugeordnet — Ramp, Card Advantage,
  Targeted Disruption, Mass Disruption oder Plan Cards (der Rest) —
  mit Unterkategorien (z. B. gliedert sich Targeted Disruption in
  Konterzauber, Entfernung, Bounce usw.) und einer separaten
  Tutoren-Liste (Tutoren schneiden quer durch die Kategorien, daher
  keine eigene Kategorie).
- **Commander-Spellbook-Combos**: gelistete Varianten, deren Karten im
  Deck enthalten sind. Der Server lädt beim ersten Aufruf den
  komprimierten Gesamtsnapshot von Commander Spellbook; spätere
  Analysen verwenden die lokale SQLite-Datenbank. Karten werden über
  den exakten Namen abgeglichen. Zusätzliche Template-Voraussetzungen
  werden angezeigt, aber nicht gegen das Deck geprüft — solche
  Varianten beeinflussen die Bracket-Schätzung nicht.

## Dynamische Analyse

Noch nicht implementiert. Diese soll später einmal Strategie,
Archetyp, Synergien und die Gesamtkohärenz eines Decks bewerten — der
Tab weist derzeit nur darauf hin.

## Bracket-Analyse

Eine **inoffizielle, heuristische Annäherung** an das
"Commander Brackets"-System von Wizards of the Coast — eine
5-stufige Skala (1 Exhibition … 5 cEDH), die die Power-Level-Erwartung
vor einem Spiel einordnen soll. Das ist **kein offizielles Urteil**,
sondern nur eine grobe Schätzung.

Nicht alle Kriterien, die Brackets unterscheiden, lassen sich aus einer
Deckliste ablesen. Dieser Tab prüft die folgenden Signale:

- **Game Changers** — Karten auf WotCs offizieller Game-Changers-Liste
  (in Bracket 1–2 gar nicht erlaubt, bis zu 3 in Bracket 3, unbegrenzt
  in 4–5).
- **Mass Land Denial** — Effekte, die allen Spielern die Länder
  entziehen (unterhalb von Bracket 4 nicht vorgesehen).
- **Extra-Turn-Karten** — als reine Anzahl gezeigt, zur eigenen
  Einschätzung; eine einzelne ist unbedenklich, verkettete/wiederholte
  sind unterhalb von Bracket 4 nicht vorgesehen.

Zwei-Karten-Infinite-Combos werden aus Commander-Spellbook-Varianten
abgeleitet, deren ausdrücklich ausgewiesene Ergebnisse "Infinite"
enthalten. Varianten mit nicht geprüften Template-Voraussetzungen
werden nicht dafür verwendet. Zur zeitlichen Einordnung vergleicht die
App die Manawerte der einzelnen Combo-Karten zugweise mit der maximalen
Mana-Kurve. Combo-Karten können über mehrere Züge ausgespielt werden;
ungenutztes Mana wird nicht übertragen, und für Ramp ausgegebenes Mana
wird nicht doppelt gezählt. Können alle Teile bis einschließlich Zug 6
ausgespielt werden, gilt die Combo als früh (geschätztes
Mindest-Bracket 4), spätere Combos als Bracket-3-Signal. Die Schätzung setzt
voraus, dass alle Combo-Karten verfügbar sind, und simuliert weder Ziehen
noch Farben oder konkrete Spielsituationen. Sie nutzt erwartete Landdrops
als Mana-Budget, nicht die Wahrscheinlichkeit einer bestimmten
Combo-Hand. Das ist eine Projekt-Heuristik,
keine offizielle numerische WotC-Definition von "früh".
Tutoren sind seit WotCs Oktober-2025-Update kein Bracket-Kriterium mehr.

Der Tab zeigt eine vorgeschlagene **Mindest-Bracket** samt Begründung,
sowie die tatsächlichen Karten hinter jedem Signal. Das Fehlen eines
Signals belegt nie, dass ein Deck in Bracket 1–3 gehört — nur die
Feinabstimmungs-Absicht (die sich nicht aus einer Liste ablesen lässt)
unterscheidet diese drei wirklich.
