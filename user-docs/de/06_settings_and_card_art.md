# 6. Einstellungen, Profil & Kartenbilder

Zwei Icon-Buttons im Kopfbereich teilen den früheren einzelnen
Einstellungs-Bildschirm in zwei Teile:

- **Einstellungen** — Server-Verbindung, lokale Daten und
  MCP-Einrichtung.
- **Profil** — alles über *dich*: dein Konto (Anmeldung, Sitzungen,
  Passwort), deine Mehrspieler-Vorgaben und alle selbst hochgeladenen Bilder.

Als Faustregel: *den Server erreichen* ist Einstellungen, *wer du bist
und wie du spielst* ist Profil.

## Einstellungen: Server-Verbindung

Unter **Einstellungen → Spielbrett** lässt sich das **Bot-Tempo** auf
**Sofort**, **Normal** oder **Langsam** setzen. Es bestimmt den Abstand zwischen
angezeigten Bot-Aktionen, wird lokal gespeichert und gilt direkt für alle
Spielansichten.

Die Anwendung verwendet automatisch die Adresse, unter der du sie geöffnet
hast. Ein Server-Adressfeld und das Speichern dieser Adresse sind nicht mehr
nötig; frühere Adress-Cookies werden ignoriert. **Verbindung testen** prüft
die Erreichbarkeit erneut. Derselbe Status erscheint im Kopfbereich.

## Einstellungen: lokale Daten aktualisieren

Den vollständigen Scryfall-Kartenpool und die Commander-Spellbook-Combo-
Datenbank aktualisiert der Server-Administrator auf der Seite `/admin` des
Server-Rechners, nicht die Spieler. (Die früheren Update-Knöpfe unter
**Lokale Daten** gibt es nicht mehr.) Die
Combo-Datenbank wird ansonsten erst bei der ersten statischen
Deckanalyse heruntergeladen. Beide Datenbestände werden serverseitig in
SQLite gespeichert; das Combo-Update zeigt die Zahl neu
hinzugefügter, geänderter und entfernter Varianten.

## Profil: die fünf Tabs

Das Profil hat fünf Tabs: **Account-Login**, **Sessions/Einladungen**,
**Passwort ändern**, **Multiplayer-Einstellungen** und
**Sleeves/Token-Bilder** (inklusive Lieblingsdecks). Solange du nicht
angemeldet bist, ist nur *Account-Login* benutzbar (Anmelden, Konto mit
Einladung anlegen, "Passwort vergessen"); die anderen Tabs sind grau und
werden mit der Anmeldung freigeschaltet. Der zuletzt gewählte Tab wird
in diesem Browser gemerkt.

Es gibt keinen frei wählbaren Spielernamen: In Spielen erscheint dein
**Kontoname**; ohne Anmeldung heißt dein Platz **"Player"**. Deine
hochgeladenen Token-Bilder, Karten-Sleeves und Lieblingsdecks gehören
zu deinem Konto; andere Spieler können sie weder sehen noch ändern.

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

Dafür musst du angemeldet sein. Hochgeladene
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
Der Server speichert komprimierte JSON-Dateien (`.json.gz`) im lokalen,
unversionierten Ordner
`bug-reports/`. Außerhalb eines Spiels werden Beschreibung und Ansicht ohne
Replay gespeichert. Der Dialog bestätigt den gespeicherten Dateinamen.
