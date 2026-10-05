# 1. Getting Started

## What this app does

DeckLab lets you:

- Paste in a Commander decklist and check it for basic legality.
- Save decks and browse them later.
- Get a detailed statistical breakdown of a deck (mana curve, land mix,
  color balance, opening-hand odds, and more).
- Get a rough, unofficial read on a deck's Commander "power bracket".
- Actually **play** a saved deck solo against a real rules engine —
  the "Goldfisch" (goldfish) mode — stepping through turns, playing
  lands, casting spells, and attacking, with every move validated
  against Magic's actual rules.
- Build an arbitrary board state from scratch (no deck required) and
  play it out — the "Puzzle/Replay" mode — handy for testing a specific
  board position or a tricky interaction.

There is no login or account system. Whatever backend server you're
pointed at (see chapter 6, "Settings") is where your saved decks and
uploaded images live — there's no per-user separation beyond a
free-text player name.

Multiplayer is implemented as a real shared-table mode: you can create
or join a lobby, set up seats and mulligans, play through normal turn
priority, and use the same rules engine as Goldfish and Replay.
Bots can also sit in empty seats, and the server keeps your seat
through reconnects.

## Starting the app

From the repository root:

```
./start.sh
```

(On Windows, use `start.bat` instead.) This sets up everything it
needs on first run and then starts a local web server. Open your
browser to **http://localhost:8765** if it doesn't open automatically.

To stop the app, press Ctrl+C in the terminal where it's running.

## Finding your way around

The sidebar on the left is grouped into sections:

- **Deck-Management** (deck management)
  - **Deck editieren** (edit deck) — paste/parse a decklist, save it
  - **Decks verwalten** (manage decks) — your saved decks: load, delete,
    check legality, pick a card sleeve
  - **Deck analysieren** (analyze deck) — statistics and the bracket
    heuristic for a saved deck
- **Singleplayer**
  - **Goldfisch** (goldfish) — play a saved deck solo against the rules
    engine
  - **Puzzle/Replay** — build and play an arbitrary board state
- **Multiplayer** — lobby setup, real shared-table play, bots, spectator
  mode and reconnect handling
- **Einstellungen** (settings) — connection status, local data and LLM configuration
- **Profil** (profile) — player name, multiplayer preferences, custom
  token art, card sleeves and favorite decks
- **Information**
  - **Karten-Cache** (card cache) — browse every card the app has
    looked up so far
  - **Engine-Status** (engine status) — a transparency page listing
    what the rules engine does and doesn't support yet

The typical flow is: **Deck editieren** → paste and save a deck →
**Decks verwalten** → load it into **Deck analysieren** and/or start it
in **Goldfisch**.

The following chapters cover each tab in more detail.
