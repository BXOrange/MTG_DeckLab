# 6. Einstellungen & Kartenbilder

Der Tab **Einstellungen** deckt deine Verbindung zum Backend-Server
und alle selbst hochgeladenen Bilder ab.

## Spielername & Server-Adresse

- **Spielername** — freier Text, ohne Konto oder Passwort dahinter.
  Er dient nur dazu, deine hochgeladenen Token-Bilder und
  Karten-Sleeves (unten) auf dem Server zuzuordnen, damit ein Gegner
  auf demselben Server in einem zukünftigen Multiplayer-Spiel sie
  ebenfalls sehen könnte.
- **Server-Adresse** — wo das Backend läuft (z. B.
  `http://localhost:8000`).

Klicke auf **Speichern**, um beides zu übernehmen — sie werden in
einem **Browser-Cookie** abgelegt, nicht serverseitig, gelten also nur
für diesen Browser/dieses Gerät; ein anderer Browser oder Rechner
startet wieder mit den Standardwerten. **Verbindung testen** prüft die
Erreichbarkeit auf Wunsch erneut; derselbe Status wird auch live im
Kopfbereich der Seite angezeigt.

## Eigene Token-Bilder

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

## Karten-Sleeves

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
