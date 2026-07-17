# 4. Goldfisch-Modus

"Goldfisch" ist Solo-Spiel gegen einen passiven Dummy-Gegner — die
klassische Art zu testen, wie sich ein Deck Zug für Zug tatsächlich
spielt. Anders als die statische Analyse aus Kapitel 3 wird hier jede
einzelne Aktion (ein Land spielen, Mana tappen, einen Zauber wirken,
angreifen …) von der echten Backend-Regel-Engine geprüft — kein
vereinfachtes Mock-Modell.

## Ein Spiel starten

1. Öffne den Tab **Goldfisch**.
2. Wähle ein gespeichertes Deck aus dem Dropdown (mit dem ⟳-Button
   die Liste aktualisieren, falls du gerade eines gespeichert hast).
3. Nur ein als ✅ **legal** markiertes Deck kann gestartet werden — ein
   nicht legales Deck zeigt 🛑 mit den Gründen, und der Start-Button
   bleibt deaktiviert.
4. Klicke auf **Goldfisch-Spiel starten**. Kartenbilder werden zuerst
   vorgeladen (Fortschrittsbalken), damit während des Spiels nichts
   nachträglich aufploppt.

## Die Starthand wählen (Mulligan)

Du erhältst 7 Karten. Von hier aus:

- **Hand behalten** — diese 7 behalten und losspielen.
- **🔀 Mulligan (neue 7 ziehen)** — ein London-Mulligan: zurückmischen
  und neue 7 ziehen. Jeder genommene Mulligan bedeutet, dass du beim
  Behalten so viele Karten unten in die Bibliothek legen musst —
  klicke Karten in deiner Hand an, um sie dafür zu markieren (eine
  laufende Zählung wie "2/2 unten ausgewählt" zeigt den Fortschritt).
- Das Häkchen **"In Zug 1 eine Karte ziehen"** bestimmt Play/Draw:
  standardmäßig bist du am Zug (keine Ziehung im ersten Zug, die
  Standardregel) — setze das Häkchen, um stattdessen im ersten Zug zu
  ziehen (wie "auf dem Draw").
- **Abbrechen** bricht ab und geht zurück zur Deckauswahl.

## Das Spielfeld

Sobald du eine Hand behältst, erscheint das interaktive Spielfeld:

- **Obere Leiste**: aktuelle Zugnummer, Phase und Schritt (z. B.
  "Hauptphase I · Ziehen").
- **Gegnerleiste** (🐟): Lebenspunkte des Goldfischs, verdeckte
  Hand-/Friedhof-/Bibliothekszahlen und jeglicher Commander-Schaden,
  den er dir zugefügt hat. Er spielt selbst nie Karten — er ist nur
  etwas, das man angreifen kann.
- **Dein Spielerbereich**: Mana-Pool und Lebenspunkte oben; eine
  Seitenspalte mit Kommandozone, Bibliothek (nur Anzahl), Friedhof und
  Exil; und der Hauptbereich mit deinem Schlachtfeld und deiner Hand.
  Mit **⇄ Zonen-Seite** lässt sich diese Spalte auf die andere Seite
  legen.
- Das **Schlachtfeld** ist standardmäßig in Reihen nach Kartentyp
  gruppiert (Kreaturen / Artefakte & Verzauberungen / Länder; über
  "Länder in eigener Reihe" gibt es eine dritte Reihe). Auren und
  Ausrüstungen werden zusammen mit dem Objekt, an dem sie hängen, in
  einem gemeinsamen Rahmen dargestellt.
- Setze das Häkchen bei **🔍 Statische Effekte**, um ein Panel
  einzublenden, das jede aktive statische Fähigkeit im Spiel sowie —
  pro betroffenem Permanent — die Layer-für-Layer-Herleitung seiner
  aktuellen Stärke/Widerstandskraft zeigt — nützlich, um zu verstehen,
  *warum* eine Kreatur gerade größer/kleiner ist oder ein zusätzliches
  Schlüsselwort hat.

## Aktionen ausführen

Direkt unter einer Karte erscheinen Buttons für alles, was sie gerade
tun kann:

- **🌳 Land spielen**
- **⟳ Tappen** für Mana — kann ein Land mehr als eine Farbe erzeugen,
  siehst du einen Button pro Option, um die Farbe zu wählen.
- **✨ Zaubern** — zeigt im Button die Manakosten, falls ein Effekt sie
  reduziert hat. Ein Zauber, der ein Ziel braucht, zeigt stattdessen
  **✨ Zaubern → Ziel ▾**; klicke darauf und wähle dann im folgenden
  Pop-up das Ziel (bzw. nacheinander mehrere, falls nötig). Ein
  Zauber mit `{X}` in den Kosten bekommt ein Zahlenfeld neben einem
  Button **✨ Zaubern (X)** — X festlegen, dann wirken.
- **⚡ [Kosten]** — eine aktivierte Fähigkeit, mit denselben
  Konventionen für Ziel/X wie beim Zaubern.
- **⚔️ Angreifen** — gibt es mehr als ein legales Ziel (z. B. mehrere
  Planeswalker), erscheint ein kleines Menü zur Wahl des
  Verteidigers.
- Eine gesperrte Aktion zeigt **🔒** mit einem Grund (z. B. "kein
  gültiges Ziel") statt eines klickbaren Buttons.

## Der Stack

Sobald etwas auf seine Auflösung wartet, legt sich ein
**Stack**-Panel über das Spielfeld und zeigt jeden ausstehenden
Zauber/jede Fähigkeit (das oberste Element löst zuerst auf). Klicke
**Priorität abgeben (Stack auflösen)**, um ihn auflösen zu lassen —
oder schiebe das Panel zunächst mit **⤡ Zur Seite schieben** beiseite,
wenn du auf dem Spielfeld darunter reagieren möchtest (z. B. einen
Spontanzauber als Antwort wirken), bevor du die Priorität abgibst.

## Entscheidungen, die das Spiel von dir verlangt

Effekte wie eine Tutor-Suche, Cascade oder Discover öffnen ein Pop-up
mit einem Button pro Option (plus, wo passend, eine Ablehnungsoption
wie "Nichts wählen"). Beantworte es, um fortzufahren — der Rest des
Spielfelds bleibt bis dahin abgedunkelt.

## Zug-Steuerung

- **Nächster Schritt →** rückt einen Schritt/eine Phase weiter.
- **⏭ Nächste Entscheidung** springt über alle Schritte ohne
  Entscheidung hinweg und hält beim nächsten Punkt, an dem tatsächlich
  eine Wahl ansteht.
- **↶ Zurücknehmen** macht die letzte Aktion rückgängig.
- **⟲ Neu starten** setzt komplett bis zu einem frischen Mulligan
  zurück.
- **⬇ Als Replay speichern** exportiert die aktuelle Spielsituation als
  Datei, die sich im Puzzle/Replay-Modus wieder öffnen lässt (siehe
  Kapitel 5) — praktisch, um eine interessante Stelle einzufrieren und
  damit zu experimentieren.
- **Beenden** beendet die Sitzung und zeigt eine Auswertung.

## Auswertung am Spielende

Ob du beendest oder das Spiel tatsächlich endet (jemand erreicht
0 Leben usw.), erhältst du pro Spieler eine Statistik: gezogene/
gespielte Karten, gewirkte Zauber, gespielte Länder, erzeugtes Mana,
durchschnittlicher Manawert und ausgeteilter/erhaltener Schaden — dazu
ein kleines Balkendiagramm der Manakurve der tatsächlich gewirkten
Zauber sowie des Manas pro Zug. **Neues Spiel** führt zurück zur
Deckauswahl.
