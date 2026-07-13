# 2. Deck-Import & gespeicherte Decks

## Eine Deckliste einlesen ("Deck editieren")

Dieser Tab hat drei separate Textfelder, und in welches Feld du eine
Karte einträgst, entscheidet über ihre Rolle im Deck — Abschnitts-
überschriften im Text sind nicht nötig:

- **Commander**
- **Mainboard** (Hauptdeck)
- **Sideboard**

Jede Zeile ist eine Karte, in einem der beiden Formate:

- `1 Sol Ring`
- `4x Mountain`

Angehängte Set-/Sammelnummer-Infos, wie sie manche Export-Tools
hinzufügen (z. B. `(LTR) 123`), werden automatisch entfernt, ebenso
Foil-/Stern-Markierungen (`★`/`☆`), die manche Seiten an einen Namen
anhängen (z. B. "Sol Ring ★"). Zeilen, die mit `#` oder `//` beginnen,
gelten als Kommentar und werden ignoriert.

Klicke auf **Deckliste parsen**, um die drei Felder einzulesen. Es
gibt außerdem einen Button **Beispieldeck laden**, der ein fertiges
Beispiel einfügt (ein Krenko-Goblin-Deck), falls du erstmal
ausprobieren möchtest.

## Was die Ergebnisanzeige zeigt

Nach dem Parsen siehst du:

- Die Gesamtkartenzahl und einen Status **Legal (strukturell)** /
  **Nicht legal**, basierend auf den strukturellen Commander-Regeln:
  genau 100 Karten insgesamt (inklusive Commander), Singleton (nur
  Basic Lands dürfen mehrfach vorkommen) und ein Commander (zwei bei
  einem Partner-Paar).
- Etwaige Parse-Fehler (eine Zeile, die nicht gelesen werden konnte)
  oder Validierungswarnungen/-fehler.
- Die Listen für Commander, Hauptdeck und Sideboard selbst.

Kurz nach dem Parsen wird dieselbe Liste zusätzlich **serverseitig**
gegen die echte Kartendatenbank der App geprüft. Dabei kommen hinzu:

- 🛑-Markierungen bei jedem Kartennamen, den der Server gar nicht
  auflösen konnte (Schreibweise prüfen).
- ❗-Markierungen bei Karten, die zwar auflösbar, aber für diesen
  Commander nicht wirklich legal sind — auf der Commander-Bannliste
  oder außerhalb der Farbidentität des Commanders. Fahre mit der Maus
  über die Markierung, um den Grund zu sehen.
- Eine Bestätigung "Serverseitig geprüft", sobald das fertig ist.

Setze das Häkchen bei **Detailansicht (Bilder & Eigenschaften)**, um
die Kartenlisten von reinem Text auf ein Raster von Kartenbild-Kacheln
umzuschalten.

## Ein Deck speichern

Vergib einen Namen im Feld **Deckname (zum Speichern)** und wähle
dann:

- **Aktualisieren** — überschreibt das aktuell geladene Deck. Nur
  aktiv, sobald schon einmal ein Deck geladen oder gespeichert wurde.
- **Als neues speichern** — legt immer ein komplett neues gespeichertes
  Deck an, lässt das geladene Deck unangetastet und springt danach auf
  die neue Kopie.

Diese beiden Buttons sind bewusst getrennt statt eines einzigen
"Speichern" — damit z. B. das Ändern des Commanders in einem geladenen
Deck nicht versehentlich das Original überschreibt.

Sobald das Deck die serverseitige Prüfung bestanden hat, erscheint am
Ende der Ergebnisanzeige ein Button **Zum Goldfisch-Modus →**, um
direkt ins Spielen einzusteigen.

## Gespeicherte Decks verwalten ("Decks verwalten")

Dieser Tab listet jedes gespeicherte Deck auf, pro Zeile mit:

- Name, Commander (👑, falls vorhanden), Farbidentitäts-Symbole (WUBRG,
  oder "C" für farblos) und Speicherzeitpunkt.
- Einer Legalitäts-Anzeige: **✅ legal** oder **🛑 nicht legal**
  (Gründe beim Draufhalten mit der Maus) — serverseitig geprüft, mit
  denselben Regeln wie oben.
- Einer **Sleeve-Auswahl** — ein eigenes Kartenrückseiten-Design für
  dieses Deck wählen (siehe Kapitel 6 zum Hochladen von Sleeves);
  Standard ist "Kein Sleeve".
- **Deck editieren** — lädt das Deck zurück in den Tab "Deck
  editieren".
- **Deck analysieren** — öffnet es im Tab "Deck analysieren" (siehe
  Kapitel 3).
- **Löschen** — fragt zur Bestätigung nach und entfernt es dann
  endgültig.

Mit **Aktualisieren** oben im Tab lässt sich die Liste neu laden (z. B.
nachdem an anderer Stelle ein neues Deck gespeichert wurde).
