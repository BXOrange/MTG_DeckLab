# 6. Einstellungen, Profil & Kartenbilder

Zwei Icon-Buttons im Kopfbereich teilen den früheren einzelnen
Einstellungs-Bildschirm in zwei Teile:

- **Einstellungen** — *nur* wie dieser Browser den Backend-Server
  erreicht.
- **Profil** — alles über *dich*: dein Spielername, deine
  Mehrspieler-Vorgaben und alle selbst hochgeladenen Bilder.

Als Faustregel: *den Server erreichen* ist Einstellungen, *wer du bist
und wie du spielst* ist Profil.

## Einstellungen: Server-Adresse

- **Server-Adresse** — wo das Backend läuft (z. B.
  `http://localhost:8000`).

Klicke auf **Speichern**, um sie zu übernehmen. Sie wird in einem
**Browser-Cookie** abgelegt, nicht serverseitig, gilt also nur für
diesen Browser/dieses Gerät; ein anderer Browser oder Rechner startet
wieder mit den Standardwerten. **Verbindung testen** prüft die
Erreichbarkeit auf Wunsch erneut; derselbe Status wird auch live im
Kopfbereich der Seite angezeigt.

## Einstellungen: lokale Daten aktualisieren

Unter **Lokale Daten** kannst du den vollständigen Scryfall-Kartenpool
und die Commander-Spellbook-Combo-Datenbank manuell aktualisieren. Die
Combo-Datenbank wird ansonsten erst bei der ersten statischen
Deckanalyse heruntergeladen. Beide Datenbestände werden serverseitig in
SQLite gespeichert; das Combo-Update zeigt die Zahl neu
hinzugefügter, geänderter und entfernter Varianten.

## Profil: Spielername

- **Spielername** — freier Text, ohne Konto oder Passwort dahinter. Er
  dient dazu, deine hochgeladenen Token-Bilder, Karten-Sleeves und
  Lieblingsdecks (unten) auf dem Server zuzuordnen, damit ein Gegner
  auf demselben Server in einem Multiplayer-Spiel deine Bilder
  ebenfalls sehen könnte.

Klicke auf **Speichern** — ebenfalls ein Browser-Cookie, pro Gerät.
Beim Speichern erhält dieser Browser außerdem eine unsichtbare
Kennung (90 Tage, verlängert sich bei jedem Speichern), damit ein
zweiter Browser mit demselben Namen nicht deinen Platz am Tisch belegt.

## Profil: Mehrspieler-Standardeinstellungen

**Mehrspieler: Standardeinstellungen** — Format, Platzanzahl,
Mulligan-Regel, Take-backs je Spieler und die Auslos-Schalter für
Regel 103.1/103.2. Sie werden automatisch auf einen Tisch übernommen,
den *du* eröffnest (im Tab **Multiplayer**); am Tisch selbst bleibt
das als Host jederzeit änderbar.

## Profil: Auto-Pass & Spielfeld-Komfort

**Mehrspieler: Auto-Pass** und **Mehrspieler: Spielfeld** — die
Komfort-Schalter dieses Browsers (Auto-Pass ein/aus, Bedenkzeit in
Sekunden, ob er auch in eigenen Zügen läuft, "sofort passen, wenn
nichts zu tun ist", und ob die gegnerische Hand als verdeckte Karten
oder bloß als Zahl gezeichnet wird). All das ist *auch* direkt am
Spielfeld während einer Partie änderbar. Was sie bewirken, steht in
Kapitel 9.

## Profil: Eigene Token-Bilder

Manche Token, die ein Effekt im Spielverlauf erzeugt, haben keine
echte Magic-Karte dahinter (z. B. ein schlichter "1/1 weißer Soldier")
und damit auch kein offizielles Bild. Unter **Eigene Token-Bilder**
kannst du ein eigenes Bild hochladen für:

- Eine bestimmte **bekannte Token-Art**, aus einem Dropdown gewählt
  (befüllt aus dem Token-Katalog der App) — z. B. ein bestimmter,
  benannter Token, den deine Decks tatsächlich erzeugen.
- **Andere …** — einen beliebigen eigenen Token-Namen von Hand
  eintippen, falls er nicht in dieser Liste steht.
- **Generisch (alle Token ohne eigenes Bild)** — ein Auffangbild für
  *jeden* Token, der weder echtes Bild noch eigenen Upload hat.

Dafür muss zuerst ein Spielername gespeichert sein. Hochgeladene
Bilder erscheinen als Kachel-Raster unter dem Formular, jeweils mit
einem **Löschen**-Button.

## Profil: Karten-Sleeves

Unter **Karten-Sleeves** kannst du eigene Kartenrückseiten-Designs
hochladen, jeweils mit einer eigenen Bezeichnung. Nach dem Hochladen
weist du im Tab **Decks verwalten** einem bestimmten gespeicherten
Deck über das Sleeve-Dropdown in dessen Zeile einen Sleeve zu.

Der Sleeve eines Decks wird als Ersatzbild für einen verdeckten oder
umgewandelten *Token* ohne eigenes Bild auf dem Spielfeld verwendet —
auf eine echte doppelseitige Karte hat er keine sichtbare Auswirkung
(diese zeigen ihre echte gedruckte Rückseite), da es aktuell keinen
modellierten verdeckten Zustand (wie Morph) gibt, der ihn bräuchte.
Betrachte es eher als Vorarbeit für später als als etwas, das sich
heute schon sichtbar auswirkt.

## Profil: Lieblingsdecks

Unter **Lieblingsdecks** kannst du eine Teilmenge deiner gespeicherten
Decks mit einem Stern markieren. Markierte Decks stehen in der
Deck-Auswahl im Goldfisch-Modus und in der Mehrspieler-Lobby zuerst.

## Fehlerberichte

Das Käfer-Symbol neben Einstellungen öffnet den Fehlerbericht. Beschreibe das
Problem und das erwartete Verhalten. Im Spiel enthält der Bericht den aktuellen
Replay und standardmäßig die letzten 12 Aktionen; die Anzahl ist anpassbar.
Der Server speichert JSON-Dateien im lokalen, unversionierten Ordner
`bug-reports/`. Außerhalb eines Spiels werden Beschreibung und Ansicht ohne
Replay gespeichert. Der Dialog bestätigt den gespeicherten Dateinamen.
