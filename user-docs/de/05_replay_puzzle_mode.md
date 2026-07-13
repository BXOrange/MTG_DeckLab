# 5. Replay-/Puzzle-Modus

**Puzzle/Replay** ist der Zwilling des Goldfisch-Modus: statt ein
legales 100-Karten-Deck zu mischen und eine Starthand zu ziehen, baust
du von Hand *jede beliebige* Spielsituation — beliebige Karten, in
beliebigen Zonen, mit beliebigen Marken, getappt/ungetappt, Leben nach
Wunsch — und spielst dann gegen dieselbe echte Regel-Engine weiter.
Nützlich, um eine bestimmte Spielzuglinie zu testen, ein Puzzle
nachzubauen oder mitten in einem Zug wieder einzusteigen.

## Starten

- **Neues Puzzle (1 Spieler)** — ein Einzelspieler-Board (kein
  Gegner).
- **Mit Gegner (2 Spieler)** — ein Zweispieler-Board.
- **Importieren …** — eine zuvor gespeicherte `.json`-Replay-Datei
  laden, auch eine, die aus einem laufenden Goldfisch-Spiel exportiert
  wurde (siehe Kapitel 4, "⬇ Als Replay speichern").

## Konfigurations-Modus (Editor)

Das ist der Standardbildschirm nach dem Start — reines Bearbeiten des
Zustands, die Zug-Engine läuft noch nicht. Die Werkzeugleiste bietet:

- **Neu** — zurück zum Startbildschirm.
- **Importieren** / **Exportieren** — das gesamte Board als
  JSON-Datei laden/speichern.
- **Beenden** — die Sitzung beenden.
- **Zug**, **Schritt**, **Aktiv** — Zugnummer, aktuellen Schritt
  (Enttappen/Versorgung/Ziehen/Hauptphasen/Kampf-Unterschritte/
  Ende/Aufräumen) und den aktiven Spieler direkt setzen, um mitten in
  einem Zug einzusteigen.
- **↶ Rückgängig** — macht auch Bearbeitungen rückgängig, nicht nur
  Spielzüge.
- **⇄ Zonen-Seite** — legt die Spalte mit Bibliothek/Friedhof/Exil/
  Kommandozone auf die andere Seite des Boards.
- **▶ Spielmodus** — schaltet auf das interaktive Board um (siehe
  unten); jederzeit über **✎ Zurück zum Editor** wieder pausierbar.

## Spielerbezogene Einstellungen

Jedes Spielerpanel hat editierbare Felder für **Leben**, **Gift**
(10 = Niederlage, wie bei jeder anderen zustandsbasierten Regel
geprüft), **Energie**/**Erfahrung**-Marken, einen **+ Marke**-Button
für jede andere benannte Marke, einen kleinen
**Mana-Pool**-Editor pro Farbe sowie erhaltenen Commander-Schaden.

## Zonen

Jeder Spieler hat: **Kommandozone**, **Bibliothek**, **Friedhof**,
**Exil**, **Schlachtfeld** (pro Spieler dargestellt, in Reihen nach
Typ gruppiert, genau wie beim Goldfisch-Board) und **Hand**.

- **+ Karte** öffnet auf jeder Zone ein Suchfeld — Namen eintippen, auf
  **Suchen** klicken, ein Ergebnis anklicken zum Hinzufügen.
- **+ Token** (nur auf dem Schlachtfeld — Token können sonst nirgendwo
  existieren) öffnet ein Formular: Name, Typzeile, Stärke/
  Widerstandskraft, Farben und optional Fähigkeitstext (echter
  Oracle-Text — z. B. bewirkt das Eintippen von "Flying" tatsächlich
  das Schlüsselwort, da die Engine ihn genauso liest wie bei einer
  echten Karte). Eine Reihe von Vorlagen (Soldier, Spirit, Angel,
  Bird, Zombie, Goblin, Dragon, Elf Warrior, Saproling, Beast, Wolf,
  Treasure, Clue, Food) füllt das Formular vor — danach weiterhin
  frei anpassbar.
- **👁 Anzeigen** bei der Bibliothek öffnet ein Pop-up mit jeder Karte
  in Zugreihenfolge, mit ▲/▼ zum Verschieben Richtung Spitze/Boden,
  einem Zone-Wechsel-Dropdown und einem ✕ zum Entfernen.

Jede Karte auf dem Board hat ihre eigene Werkzeugleiste:

- **⤵** tappen/enttappen
- **⟳** umwandeln (eine doppelseitige Karte flippen)
- **＋** / **−** eine +1/+1- oder −1/−1-Marke hinzufügen
- **✦** jede andere benannte Marke (du wirst nach Name und Anzahl
  gefragt)
- ein **→ Zone …**-Dropdown, um die Karte in jede Zone eines
  beliebigen Spielers zu verschieben
- **✕** die Karte vollständig entfernen

## Spielmodus

Ein Klick auf **▶ Spielmodus** übergibt das Board an dieselbe
interaktive Ansicht, die auch der Goldfisch-Modus nutzt (Kapitel 4):
Ab hier läuft die Zug-Engine tatsächlich, und Länder spielen/Zaubern/
Angreifen/der Stack/anstehende Entscheidungen funktionieren genauso.
**✎ Zurück zum Editor** pausiert die Zug-Engine und bringt dich
jederzeit zurück in den freien Bearbeitungsmodus — beim Hin- und
Herwechseln geht nichts vom Zustand verloren.

## Deinen Stand speichern

**Exportieren** lädt die gesamte Situation als `.json`-Datei herunter;
**Importieren** lädt eine solche Datei später wieder, in der
Werkzeugleiste beider Modi. So übergibt auch ein Goldfisch-Spiel an
Puzzle/Replay: im Goldfisch-Modus exportieren, dieselbe Datei hier
importieren und die Situation frei weiter erkunden.
