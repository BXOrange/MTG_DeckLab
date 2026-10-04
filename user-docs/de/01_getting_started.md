# 1. Erste Schritte

## Was diese App kann

DeckLab ermöglicht dir:

- Eine Commander-Deckliste einzufügen und auf grundlegende Legalität
  zu prüfen.
- Decks zu speichern und später wiederzufinden.
- Eine detaillierte statistische Auswertung eines Decks zu erhalten
  (Manakurve, Land-Mix, Farbbalance, Starthand-Wahrscheinlichkeiten
  und mehr).
- Eine grobe, inoffizielle Einschätzung der Commander-"Power-Bracket"
  eines Decks zu bekommen.
- Ein gespeichertes Deck tatsächlich **solo gegen eine echte
  Regel-Engine zu spielen** — der "Goldfisch"-Modus — Zug für Zug,
  mit Ländern spielen, Zaubern wirken und Angreifen, wobei jeder Zug
  gegen die echten Magic-Regeln geprüft wird.
- Einen beliebigen Spielzustand von Grund auf zu bauen (kein Deck
  nötig) und daraus zu spielen — der "Puzzle/Replay"-Modus — praktisch,
  um eine bestimmte Boardsituation oder eine knifflige Interaktion zu
  testen.

Es gibt kein Login und kein Benutzerkonto. Auf welchem Backend-Server
du gerade eingestellt bist (siehe Kapitel 6, "Einstellungen"), dort
liegen deine gespeicherten Decks und hochgeladenen Bilder — es gibt
keine Trennung nach Benutzer über einen frei eingegebenen Spielernamen
hinaus.

Multiplayer ist als echter Shared-Table-Modus umgesetzt: Du kannst
Lobbys erstellen oder beitreten, Plätze und Mulligans einstellen,
über echte Prioritätsfenster spielen und denselben Regel-Engine-Stack
wie im Goldfisch und im Replay nutzen. Auch Bots können freie Plätze
besetzen, und der Server hält deinen Sitz bei Verbindungsabbrüchen.
./start.sh
```

(Unter Windows stattdessen `start.bat`.) Beim ersten Start wird alles
Nötige eingerichtet, danach startet ein lokaler Webserver. Öffne
deinen Browser unter **http://localhost:8765**, falls sich kein Tab
automatisch öffnet.

Zum Beenden im Terminal, in dem die App läuft, Strg+C drücken.

## Orientierung in der App

Die Seitenleiste links ist in Gruppen unterteilt:

- **Deck-Management**
  - **Deck editieren** — Deckliste einfügen/einlesen, speichern
  - **Decks verwalten** — deine gespeicherten Decks: laden, löschen,
    Legalität prüfen, ein Karten-Sleeve wählen
  - **Deck analysieren** — Statistiken und die Bracket-Heuristik für
    ein gespeichertes Deck
- **Singleplayer**
  - **Goldfisch** — ein gespeichertes Deck solo gegen die Regel-Engine
    spielen
  - **Puzzle/Replay** — einen beliebigen Spielzustand bauen und spielen
- **Multiplayer** — Lobby-Setup, echtes Shared-Table-Spiel, Bots,
  Zuschauer-Modus und Wiederanbindung
- **Einstellungen** — Verbindungsstatus, lokale Daten und LLM-Konfiguration
- **Profil** — Spielername, Mehrspieler-Vorgaben, eigene Token-Bilder,
  Karten-Sleeves und Lieblingsdecks
- **Information**
  - **Karten-Cache** — alle bisher abgefragten Karten durchsuchen
  - **Engine-Status** — eine Übersichtsseite, was die Regel-Engine
    bereits unterstützt und was noch fehlt

Der typische Ablauf: **Deck editieren** → Deckliste einfügen und
speichern → **Decks verwalten** → in **Deck analysieren** laden
und/oder im **Goldfisch**-Modus starten.

Die folgenden Kapitel gehen auf jeden Tab im Detail ein.
