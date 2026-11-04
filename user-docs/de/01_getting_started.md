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

Decks speichern, Bilder hochladen und Multiplayer spielen brauchen ein
**Konto** auf dem Server, auf den du eingestellt bist (siehe Kapitel 6,
"Einstellungen"): Du legst es unter **Profil → Account-Login** mit einem
Einladungs-Token von jemandem an, der schon ein Konto hat (oder von der
Person, die den Server betreibt). Deine gespeicherten Decks und
hochgeladenen Bilder gehören zu deinem Konto, niemand sonst sieht sie.
Die globalen Decks, die Deck-Analyse sowie Goldfisch, Solo und Replay
funktionieren auch ohne Anmeldung. Einen frei wählbaren Spielernamen gibt
es nicht: Dein Kontoname ist der Name, den andere Spieler sehen. Auf dem
eigenen Rechner startet `./start.sh --localdev` einen Modus, in dem du
automatisch als eingebauter Spieler "local" angemeldet bist.

Multiplayer ist als echter Shared-Table-Modus umgesetzt: Du kannst
Lobbys erstellen oder beitreten, Plätze und Mulligans einstellen,
über echte Prioritätsfenster spielen und denselben Regel-Engine-Stack
wie im Goldfisch und im Replay nutzen. Auch Bots können freie Plätze
besetzen, und der Server hält deinen Sitz bei Verbindungsabbrüchen.
./start.sh
```

(Unter Windows stattdessen `start.bat`.) Beim ersten Start wird alles
Nötige eingerichtet, danach startet der Webserver. Öffne
deinen Browser unter **http://localhost:8765**, falls sich kein Tab
automatisch öffnet. Standardmäßig nimmt der Server Verbindungen aus dem
lokalen Netz (und von diesem Rechner) an und verlangt Konten; wer ihn
betreibt, folgt der [Server-Anleitung](../../docs/Reference/SERVER_GUIDE.md).
Andere Geräte öffnen `http://<Adresse des Servers>:8000`.

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
- **Einstellungen** — Verbindungsstatus, lokale Daten und MCP-Einrichtung
- **Profil** — Konto (Anmeldung, Sitzungen, Passwort), Mehrspieler-Vorgaben, eigene Token-Bilder,
  Karten-Sleeves und Lieblingsdecks
- **Information**
  - **Karten-Cache** — alle bisher abgefragten Karten durchsuchen
  - **Engine-Status** — eine Übersichtsseite, was die Regel-Engine
    bereits unterstützt und was noch fehlt

Der typische Ablauf: **Deck editieren** → Deckliste einfügen und
speichern → **Decks verwalten** → in **Deck analysieren** laden
und/oder im **Goldfisch**-Modus starten.

Die folgenden Kapitel gehen auf jeden Tab im Detail ein.
