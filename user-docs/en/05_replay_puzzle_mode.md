# 5. Replay/Puzzle Mode

**Puzzle/Replay** is Goldfisch's sibling: instead of shuffling up a
legal 100-card deck and drawing an opening hand, you build *any* board
state by hand — any cards, in any zone, with any counters/tapped
state/life totals — and then play from there against the same real
rules engine. Useful for testing a specific line, recreating a puzzle,
or picking up a game mid-turn.

## Starting

- **Neues Puzzle (1 Spieler)** — a single-player board (no opponent).
- **Mit Gegner (2 Spieler)** — a two-player board.
- **Importieren…** (import) — load a previously saved `.json` replay
  file, including one exported from a running Goldfisch game (see
  chapter 4's "⬇ Als Replay speichern").

## Editor mode (Konfigurations-Modus)

This is the default screen after starting — pure state editing, the
turn engine isn't running yet. The toolbar offers:

- **Neu** (new) — quit back to the start screen.
- **Importieren** / **Exportieren** — load/save the whole board as a
  JSON file.
- **Beenden** (quit) — end the session.
- **Zug** (turn), **Schritt** (step), **Aktiv** (active player) — set
  the turn number, current step (untap/upkeep/draw/main/combat
  sub-steps/end/cleanup), and whose turn it is directly, to drop
  yourself into the middle of a turn.
- **↶ Rückgängig** (undo) — undoes the last edit too, not just gameplay
  actions.
- **⇄ Zonen-Seite** (flip zone side) — moves the library/graveyard/
  exile/command-zone column to the other side of the board.
- **▶ Spielmodus** (play mode) — switches to the interactive board (see
  below); pauses again any time via **✎ Zurück zum Editor** (back to
  editor).

## Per-player controls

Each player panel has editable fields for **Leben** (life), **Gift**
(poison — 10 is a loss, checked like any other state-based rule),
**Energie**/**Erfahrung** (energy/experience counters), a **+ Marke**
(add counter) button for any other named counter, a small per-color
**Mana-Pool** editor, and any commander damage received.

## Zones

Each player has: **Kommandozone**, **Bibliothek** (library),
**Friedhof** (graveyard), **Exil** (exile), **Schlachtfeld**
(battlefield — shared visually per player, split into rows by type
just like the Goldfisch board), and **Hand**.

- **+ Karte** (add card) on any zone opens a search box — type a name,
  hit **Suchen** (search), click a result to add it.
- **+ Token** (battlefield only — tokens can't exist anywhere else)
  opens a form: name, type line, power/toughness, colors, and optional
  oracle text (real oracle text — e.g. typing "Flying" actually grants
  the keyword, since the engine reads it the same way it reads a real
  card). A row of presets (Soldier, Spirit, Angel, Bird, Zombie,
  Goblin, Dragon, Elf Warrior, Saproling, Beast, Wolf, Treasure, Clue,
  Food) pre-fills the form — still fully editable afterward.
- **👁 Anzeigen** (view) on the library opens a popup listing every
  card in draw order, with ▲/▼ to nudge a card toward the top/bottom,
  a move-to-zone dropdown, and a ✕ to remove it.

Every card on the board has its own toolbar:

- **⤵** tap/untap
- **⟳** transform (flip a double-faced card)
- **＋** / **−** add a +1/+1 or −1/−1 counter
- **✦** any other named counter (you'll be prompted for its name and
  amount)
- a **→ Zone…** dropdown to move it to any zone, of either player
- **✕** remove it entirely

## Play mode (Spielmodus)

Clicking **▶ Spielmodus** hands the board over to the same interactive
view Goldfisch uses (chapter 4): the turn engine actually runs from
here, and playing lands/casting/attacking/the stack/pending choices
all work exactly the same way. **✎ Zurück zum Editor** pauses the turn
engine and drops you back into free editing at any time — nothing
about the state is lost switching back and forth.

## Saving your work

**Exportieren** downloads the whole position as a `.json` file;
**Importieren** loads one back later, in either mode's toolbar. This
is also how a Goldfisch game hands off to Puzzle/Replay: export it
from Goldfisch, then import that same file here to keep exploring the
position freely.
