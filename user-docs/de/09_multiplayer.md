# 9. Multiplayer

Im **Multiplayer** spielen zwei Personen eine echte Partie gegeneinander —
gegen dieselbe Regel-Engine, die auch Goldfisch und Puzzle/Replay
antreibt. Beide öffnen die App in ihrem eigenen Browser und zeigen auf
denselben Backend-Server (siehe Kapitel 6, **Einstellungen** —
Server-Adresse).

Die Sidebar-Gruppe **Multiplayer** hat zwei Einträge:

- **Setup** — die Lobby: wer verbunden ist, welche Spiele es gibt und das
  Panel, in dem eine Partie eingerichtet wird.
- **Board** — die Partie selbst. Der Tab bleibt ausgegraut, solange du an
  keinem Tisch sitzt; sobald ein Spiel startet, wechselt die App
  automatisch dorthin.

## Vorbereitung

Trage deinen Spielernamen im Tab **Profil** ein. Das ist der Name, den
die anderen in der Lobby sehen. Er ist reine Beschriftung — die App hat
keine Konten und keine Passwörter —, zwei Personen mit demselben Namen
sind also trotzdem zwei verschiedene Spieler.

Außerdem brauchst du mindestens ein als **legal** gespeichertes Deck
(Kapitel 2). Es gilt dieselbe Regel wie im Goldfisch-Modus: Ein nicht
legales Deck kann nicht an den Tisch.

## Die Lobby (Setup)

Öffne **Setup**. Die App verbindet sich mit dem Server, und du erscheinst
rechts in der Liste **Spieler**. Jeder dort hat einen von drei Zuständen:

- 🟡 **Online** — verbunden, aber gerade woanders in der App.
- 🟢 **Verfügbar** — in der Lobby, in keinem Spiel.
- 🔵 **Im Spiel** — an einem Tisch, als Spieler oder als Zuschauer.

Links zeigt **Spiele** jeden Tisch: seinen Status — *in Vorbereitung*,
*läuft* oder *beendet* —, wie viele Plätze belegt sind und wer dort
sitzt.

### Ein Spiel erstellen

Gib im Kasten **Neues Spiel** optional einen Namen ein und klicke auf
**Spiel erstellen**. Du wirst Host 👑 des Tisches und nimmst den ersten
Platz ein. Unterstützt werden zwei Spieler.

### Einem Spiel beitreten

Klicke bei einem Tisch, der noch *in Vorbereitung* ist und einen freien
Platz hat, auf **Beitreten**.

### Einem Spiel zuschauen

Klicke bei einem laufenden Tisch auf **👁️ Zuschauen** — siehe
"Beobachter-Modus" weiter unten.

## Die Partie einrichten

Sobald du an einem Tisch sitzt, erscheint oben in **Setup** ein Panel mit:

- **Den Plätzen**, in Zugreihenfolge. Platz 1 beginnt. Jede Zeile zeigt
  den Spieler, sein gewähltes Deck und ob er schon zugesagt hat. 👑
  markiert den Host, "(du)" dich selbst.
- **Mulligan-Regel** — vom Host für den ganzen Tisch gewählt:
  - *London-Mulligan* (Standard): zurückmischen und neue 7 ziehen; beim
    Behalten so viele Karten unten in die Bibliothek legen, wie Mulligans
    genommen wurden.
  - *Next 7*: zurückmischen und neue 7 ziehen, genau wie beim
    London-Mulligan — aber beim Behalten wird nie unterlegt, egal wie
    viele Mulligans genommen wurden. Eine "freie" Variante für lockeres
    Spiel/Playtesting.
  - *Kein Mulligan*: die Starthand wird behalten.
- **Take-backs je Spieler** — vom Host für den ganzen Tisch gewählt
  (Standard: 0, also aus). Erlaubt jedem Platz, im laufenden Spiel seinen
  eigenen letzten Zug zurückzunehmen — für Fehlklicks, nicht als
  allgemeine Undo-Funktion. Da alle Spieler eine gemeinsame Zeitleiste
  teilen, nimmt das Zurücknehmen deines Zuges automatisch auch alles mit
  zurück, was der Gegner *seitdem* gemacht hat.
- **Dein Deck** — eines deiner gespeicherten Decks. Jeder wählt selbst.
- **✔ Bereit** — deine Zusage. Ohne Deck nicht möglich.
- **▶ Spiel starten** — nur der Host, und erst wenn alle Plätze belegt
  sind und alle zugesagt haben.
- **Verlassen** — den Platz aufgeben.

Alles, was den Tisch verändert — jemand tritt bei oder geht, ein Deck
wird gewechselt, die Mulligan-Regel ändert sich — setzt die Zusage
**aller** zurück. So kann niemand in eine Partie geraten, der er nicht
zugestimmt hat. Einfach erneut auf **Bereit** klicken.

Startet der Host das Spiel, werden alle Spieler automatisch zum Tab
**Board** geschaltet.

### Einen Bot einsetzen

Ist noch ein Platz frei, kann der **Host** ihn mit einem Bot besetzen —
für ein Spiel allein gegen den Computer, oder um ohne zweite Person zu
testen. Im Panel erscheint dazu die Zeile **Bot einsetzen** mit einer
Auswahl und der Schaltfläche **🤖 Hinzufügen**:

- **Goldfisch-Bot** — spielt nur Länder und passt sonst immer. Der
  klassische "Goldfisch": ein Gegner, der nichts tut, ideal um die eigene
  Kurve zu testen.
- **Gieriger Bot** — spielt alles, sobald er es spielen kann, greift mit
  allem an, blockt mit allem und wählt immer das erstbeste Ziel. Er
  optimiert nichts; er ist ein Gegner, der Druck macht, kein guter
  Spieler.

Ein Bot sitzt danach wie jeder andere in der Platzliste (mit 🤖 markiert).
Zwei Dinge macht der Host für ihn, weil ein Bot keine eigene Ansicht hat:

- **Sein Deck wählen** — direkt in seiner Platzzeile. Sobald der Bot ein
  Deck hat, gilt er als *bereit*.
- **Ihn wieder entfernen** — mit dem **✕** in seiner Zeile.

Danach läuft alles wie sonst: **▶ Spiel starten**, und der Bot behält
seine Starthand und zieht seine Züge von selbst. Sein ganzer Zug erscheint
bei dir in einem Rutsch, sobald du am Zug bist. Ein Tisch, an dem nur
noch Bots sitzen, wird aufgelöst — Bots spielen nicht allein weiter, und
sie können auch niemanden einladen oder ein Spiel starten.

## Spielen

### Die Starthand

Jeder Spieler wählt seine Starthand unabhängig auf seinem eigenen
Bildschirm: **Hand behalten** oder **🔀 Mulligan**, genau wie im
Goldfisch-Modus (Kapitel 4). Wer behalten hat, sieht, auf wen der Tisch
noch wartet. Losgespielt wird, wenn alle behalten haben.

Play/Draw ist hier keine Wahl: Platz 1 beginnt und lässt seine erste
Ziehung aus, wie es die normalen Regeln vorsehen.

### Das Spielfeld

Das Spielfeld ist dasselbe wie im Goldfisch-Modus (Kapitel 4 beschreibt
Zonen, Kartenbuttons, den Stack und die Ziel-Dialoge), mit einigen
Unterschieden für eine gemeinsame Partie:

- **Dein eigenes Board liegt unten**, dir am nächsten; das des Gegners
  darüber. Dein Platz trägt das Abzeichen **DU**, wer am Zug ist, das
  Abzeichen **AM ZUG**.
- **Du siehst nur deine eigene Hand.** Die Hand des Gegners erscheint als
  verdeckte Karten — so viele, wie er hält. Das ist nicht nur eine
  Anzeigefrage: Seine Karten werden gar nicht erst an deinen Browser
  geschickt. Von seiner Bibliothek siehst du nur die Anzahl — und von
  deiner eigenen ebenfalls (auch du kennst deine Zugreihenfolge nicht).
- **Es gibt keinen "Nächster Schritt"-Button.** Der Zug schreitet voran,
  weil die Spieler die Priorität weitergeben, nicht weil jemand einen
  Schritt für beendet erklärt — siehe "Priorität" unten.
- **Es gibt kein "Zurücknehmen" und keine "Nächste Entscheidung".** Beides
  sind Solo-Hilfen: In einer gemeinsamen Partie kann man keinen Zug
  einseitig zurücknehmen, und Schritte zu überspringen würde auch die
  Reaktionsfenster des Gegners überspringen.
- Trifft der Gegner gerade eine Entscheidung, siehst du **"… trifft
  gerade eine Entscheidung"** statt seiner Optionen — die könnten Karten
  verraten, die du nicht sehen darfst.

### Priorität

Magic geht nicht Schritt für Schritt weiter, weil jemand auf "weiter"
klickt, sondern weil alle Spieler der Reihe nach gesagt haben: "Ich möchte
gerade nichts tun." Das ist die *Priorität* (Regel 117), und das
Multiplayer-Spielfeld setzt sie richtig um.

Der Hauptbutton heißt **Passen**. Er ist nur aktiv, wenn du dran bist;
daneben steht entweder **"Du bist dran (Priorität)"** oder **"⏳ X ist
dran …"**. Was beim Passen geschieht:

- Hat noch jemand nicht gepasst, geht die Priorität an diese Person weiter.
  Sonst ändert sich nichts — sie ist jetzt mit Reagieren dran.
- Haben alle gepasst und **liegt etwas auf dem Stack**, löst sich das
  oberste Objekt auf; danach ist der aktive Spieler wieder dran, damit
  alle auf das Geschehene reagieren können.
- Haben alle gepasst und **ist der Stack leer**, endet der Schritt und der
  nächste beginnt.

Sobald du irgendetwas tust — ein Land spielen, einen Zauber wirken, eine
Fähigkeit aktivieren —, bekommst du die Priorität zurück, und alle
bisherigen Pässe verfallen: Das Spiel hat sich geändert, also bekommen die
anderen eine neue Gelegenheit zu reagieren.

Solange du nicht dran bist, haben deine Karten keine Buttons — der Server
nimmt von einem Spieler ohne Priorität keine Aktion an. Die einzige
Ausnahme ist das Deklarieren von Blockern, das gar nicht mit Priorität
geschieht.

### Auto-Pass

Zweimal pro Schritt zu passen wird schnell zäh, wenn ohnehin niemand
reagieren will. Deshalb gibt es einen Countdown: Solange du die Priorität
hast, läuft neben dem Abzeichen eine Zeit herunter und passt bei **0**
automatisch für dich.

- **Standardmäßig an**, mit **3 Sekunden**.
- **Jede Aktion auf dem Spielfeld stoppt ihn** für dieses Fenster — sobald
  du irgendwo klickst, wird die Zahl durchgestrichen und der Countdown ist
  vorbei. Er kann dir also nicht mitten im Überlegen dazwischenfunken.
- Standardmäßig läuft er **nur in gegnerischen Zügen**, also dort, wo du
  reagierst. Dein eigener Zug bleibt vollständig unter deiner Kontrolle.
  Wer lieber ein durchgehend festes Tempo möchte, kann auf "alle Züge"
  umstellen.

Alle drei Einstellungen stehen unter **Einstellungen**; Ein/Aus und die
Sekundenzahl findest du zusätzlich direkt am Spielfeld, damit du sie
mitten in der Partie ändern kannst — meist genau in dem Moment, in dem der
Auto-Pass dich gerade eine Reaktion gekostet hat.

### Was am Spielfeld sonst noch einstellbar ist

- **Gegnerische Hand**: standardmäßig steht in der Handzone des Gegners
  nur die *Anzahl* ("5 verdeckte Karten"). Die Karten selbst bekommt dein
  Browser ohnehin nie zu sehen (Regel 400.2 – der Server schickt sie gar
  nicht erst mit), die Kartenrücken kosteten nur Platz. Über das Häkchen
  **verdeckte Karten zeigen** an der Handzone (oder in den
  **Einstellungen**) bekommst du sie zurück. Karten, die ein Effekt
  wirklich *aufdeckt*, werden immer angezeigt.
- **⏭ Nächste Aktion**: passt alle Prioritätsfenster durch, in denen dir
  überhaupt keine Handlung offensteht, und hält beim ersten Fenster, in
  dem du wirklich etwas tun kannst. Das Häkchen **Leere Fenster
  überspringen** macht daraus einen Dauerzustand. Das ist bewusst etwas
  anderes als Auto-Pass: Auto-Pass zählt herunter, *weil* du hättest
  reagieren können – hier gibt es nichts abzuwarten.
- **Passen am eigenen Brett**: der Passen-Knopf und die Anzeige „Du bist
  dran" stehen zusätzlich auf der Kopfzeile deines eigenen Spielfelds –
  bei zwei Brettern ist die Leiste ganz oben meist aus dem Bild gescrollt.
- **Zug-Zähler**: „Zug 4" meint die vierte Runde, also das vierte Mal, dass
  der Startspieler an der Reihe ist. Die regeltechnische Zählung (Regel
  500.1 zählt jeden einzelnen Spielerzug) steht im Tooltip.
- **Spielerwerte**: Gift (Regel 704.5c), Energie-/Erfahrungs-/
  Strahlungsmarken, der Eine Ring, Monarch/Initiative und Embleme stehen
  neben den Lebenspunkten in der Kopfzeile des jeweiligen Spielers.

### Blocken

Wirst du angegriffen, erscheint im Blocker-Schritt über dem Spielfeld das
Panel **🛡️ Blocker deklarieren**. Es listet jede deiner Kreaturen auf, die
blocken könnte, jeweils mit einer Auswahl der Angreifer, denen sie
regelkonform zugewiesen werden darf — Ausweich-Fähigkeiten, Schutz und
ähnliche Einschränkungen sind bereits herausgefiltert. Was die Auswahl
anbietet, ist also ein legaler Block.

Weise so viele Kreaturen zu, wie du möchtest, und klicke auf **Block
bestätigen**. Der gesamte Block wird auf einmal deklariert — genau das
macht Mehrfachblocks möglich: Ein Angreifer mit *Bedrohlich* etwa muss
von zwei oder mehr Kreaturen geblockt werden, und das lässt sich nur an
der vollständigen Zuweisung prüfen. **Zurücksetzen** verwirft deine
Auswahl.

Willst du komplett auf einen Block verzichten, ist das eine ganz normale,
gültige Entscheidung: weise einfach nichts zu und klicke trotzdem auf den
Bestätigen-Knopf (er heißt dann **Keine Blocker bestätigen**).

### Zug zurücknehmen

Hat der Host beim Einrichten der Partie **Take-backs je Spieler** auf
mehr als 0 gesetzt, erscheint am Spielfeld neben **Aufgeben** der Button
**↩️ Zug zurücknehmen (N)** — N ist dein noch verbleibendes Kontingent.
Ein Klick macht deinen letzten eigenen Zug ungeschehen und zieht eins von
deinem Kontingent ab. Da alle an einem Tisch eine gemeinsame Zeitleiste
teilen, macht das Zurücknehmen automatisch auch alles rückgängig, was der
Gegner seit deinem letzten Zug getan hat — dafür ist das Kontingent
begrenzt, damit daraus keine allgemeine Undo-Funktion wird.

### Aufgeben

**🏳️ Aufgeben** auf dem Spielfeld beendet deine Partie; du wirst noch um
Bestätigung gebeten. In einer Zweierpartie endet damit sofort das ganze
Spiel, und der andere Spieler gewinnt.

Aufgeben ist jederzeit erlaubt, wird aber wie am echten Tisch
üblicherweise zu Hexerei-Zeitpunkten gemacht — im eigenen Zug, mit leerem
Stack.

### Spielende

Endet die Partie — durch Aufgabe, durch 0 Lebenspunkte oder durch eine
andere regelbedingte Niederlage —, sehen beide Spieler dieselbe
Auswertung wie im Goldfisch-Modus (Kapitel 4): wer gewonnen hat, dazu die
Statistik pro Spieler mit Mana-Kurve und Mana-pro-Zug-Diagramm. **Zurück
in die Lobby** gibt deinen Platz frei und bringt dich zurück ins Setup.

## Beobachter-Modus

**👁️ Zuschauen** an einem laufenden Tisch setzt dich als Beobachter dazu.
Du siehst das vollständige öffentliche Spielfeld — Schlachtfelder,
Lebenspunkte, Manapools, Marken, Friedhöfe, Exil, Kommandozonen,
Bibliotheks-Anzahlen und den Stack — und **niemandes Hand**, auch nicht
kurz. Oben weist ein Hinweis darauf hin, dass du zuschaust; Spielaktionen
gibt es keine. **Zuschauen beenden** bringt dich zurück in die Lobby.

## Verbindungsabbruch

Ein Neuladen der Seite, ein zugeklappter Laptop oder ein wackeliges Netz
kosten dich nicht die Partie.

**Dein Platz wird über deinen Spielernamen reserviert.** Komm mit
demselben Namen im Profil-Tab zurück, und du sitzt wieder auf demselben
Platz, mit dem Spielstand von vorher — das Spielfeld wird dabei vom Server
neu aufgebaut, du kannst also nicht "auseinanderlaufen". Die App verbindet
sich von selbst neu; meistens passiert das einfach.

Während du weg bist:

- Die anderen sehen auf deinem Board **⚡ getrennt** und einen Hinweis in
  der Lobby, wissen also, warum du gerade nichts tust.
- **Der Server passt für dich**, damit das Spiel nicht auf jemanden
  wartet, der nicht da ist. Er passt ausschließlich — gespielt wird nie
  etwas für dich.
- Dein Platz bleibt für eine Karenzzeit reserviert (standardmäßig 90
  Sekunden). Kommst du nicht rechtzeitig zurück, wird der Platz
  freigegeben; das zählt als Aufgeben.

Der Server trennt außerdem eine Verbindung, die den Tisch aufhält: Wer die
Priorität hat und (standardmäßig) zwei Minuten lang gar nichts tut, wird
getrennt, und die Karenzzeit oben beginnt. Das richtet sich nicht gegen
langsames Spielen — es geht um einen Browser-Tab, der ohne Abmeldung
gestorben ist und die Partie sonst für immer blockieren würde. Mit
aktivem Auto-Pass erreichst du diese Grenze nie.

Wer den Server betreibt, kann beide Zeiten über Umgebungsvariablen
einstellen: `MTG_MULTIPLAYER_IDLE_TIMEOUT` (Sekunden bis zur Trennung bei
Inaktivität, Standard 120) und `MTG_MULTIPLAYER_DISCONNECT_GRACE`
(Sekunden, die ein Platz reserviert bleibt, Standard 90). Der Wert `0`
schaltet die jeweilige Zeit ab.

## Hinweise und Grenzen

- **Zwei Spieler.** Mehr Plätze werden noch nicht unterstützt (ein Bot
  belegt einen davon).
- **Namen sind Identitäten — und ungeschützt.** Zwei Personen mit
  demselben Namen gelten als derselbe Spieler, und wer sich zuletzt
  verbindet, übernimmt den Platz. Gebt euch am Tisch also unterschiedliche
  Namen.
- **Alles liegt im Arbeitsspeicher.** Ein Neustart des Backend-Servers
  verwirft die Lobby und jede laufende Partie.
- Was du gerade angefangen hattest — ein Ziel-Dialog, ein halb
  zusammengestellter Block — geht beim Wiederverbinden verloren.
  Wiederhergestellt werden nur abgeschlossene Züge.
