# 4. Goldfish Mode

"Goldfisch" (goldfish) is solo play against a passive dummy opponent —
the classic way to test how a deck actually plays out, turn by turn.
Unlike the static analysis in chapter 3, every single action here (playing
a land, tapping mana, casting a spell, attacking, …) is validated by
the actual backend rules engine — not a simplified mock.

## Starting a game

1. Open the **Goldfisch** tab.
2. Pick a saved deck from the dropdown (use the ⟳ button to refresh
   the list if you just saved one).
3. Only a deck marked ✅ **legal** can be started — an illegal deck
   shows 🛑 with the reasons, and the start button stays disabled.
4. Click **Goldfisch-Spiel starten** (start goldfish game). Card
   images are preloaded first (progress bar) so nothing pops in
   mid-game.

## Choosing your opening hand (mulligan)

You're dealt 7 cards. From here:

- **Hand behalten** (keep hand) — keep these 7 and start playing.
- **🔀 Mulligan (7 Karten ziehen)** (draw 7 cards) — a London mulligan:
  shuffle back and draw a fresh 7. Each mulligan you've taken means
  that, when you do keep a hand, you must put that many cards on the
  bottom of your library first — click cards in your hand to mark them
  for the bottom (you'll see a running count like "2/2 unten
  ausgewählt").
- The checkbox **"In Zug 1 eine Karte ziehen"** (draw a card on turn 1)
  controls play/draw: by default you're on the play (no draw on your
  first turn, the standard rule) — check it to draw on turn 1 instead
  (as if you were "on the draw").
- **Abbrechen** (cancel) quits back to the deck picker.

## The board

Once you keep a hand, the interactive board appears:

- **Top bar**: current turn number, phase and step (e.g. "Hauptphase I
  · Ziehen" — main phase / draw step).
- **Opponent strip** (🐟): the goldfish's life total, hidden hand/
  graveyard/library counts, and any commander damage it's dealt you.
  It never plays cards itself — it's just something to attack.
- **Your player board**: mana pool and life total at the top; a side
  column with Command Zone, Bibliothek (library, count only),
  Friedhof (graveyard), and Exil (exile); and the main area with your
  battlefield and hand. Use **⇄ Zonen-Seite** to flip which side that
  column sits on.
- The **battlefield** is grouped into rows by card type (creatures /
  artifacts & enchantments / lands by default; check "Länder in
  eigener Reihe" (lands in their own row) for a third row). Auras and
  Equipment are drawn framed together with whatever they're attached
  to.
- Check **🔍 Statische Effekte** (static effects) to reveal a panel
  listing every active static ability in play and, per affected
  permanent, the layer-by-layer derivation of its current power/
  toughness — useful for understanding *why* a creature is currently
  bigger/smaller or has an extra keyword.

## Taking actions

Buttons appear directly under a card for whatever it can currently do:

- **🌳 Land spielen** (play land)
- **⟳ Tappen** (tap) for mana — if a land can produce more than one
  color, you'll see one button per option so you choose which color.
- **✨ Zaubern** (cast) — shows the mana cost in the button if it's
  been reduced by some effect. A spell that needs a target instead
  shows **✨ Zaubern → Ziel ▾** (cast → target); click it, then pick
  the target(s) in the popup that follows (one at a time, if it needs
  several). A spell with `{X}` in its cost gets a number field next to
  a **✨ Zaubern (X)** button — set X, then cast.
- **⚡ [cost]** — an activated ability, following the same
  target/X conventions as casting.
- **⚔️ Angreifen** (attack) — if there's more than one legal target
  (multiple planeswalkers, say), you'll get a small menu to choose the
  defender.
- A locked action shows **🔒** with a reason (e.g. "kein gültiges
  Ziel" — no legal target) instead of a clickable button.

## The stack

Whenever something is waiting to resolve, a **Stack** panel overlays
the board showing every pending spell/ability (top item resolves
first). Click **Priorität abgeben (Stack auflösen)** ("pass priority
(resolve stack)") to let it go through — or push the panel aside with
**⤡ Zur Seite schieben** (push aside) first if you want to act on the
board underneath (e.g. cast an instant in response) before passing.

## Choices the game asks you to make

Effects like a tutor search, Cascade, or Discover open a popup with
one button per option (plus a decline option where relevant, e.g.
"Nichts wählen" — choose nothing). Answer it to continue; the rest of
the board is dimmed until you do.

## Turn controls

- **Nächster Schritt →** (next step) advances one phase/step at a
  time.
- **⏭ Nächste Entscheidung** (next decision) fast-forwards through any
  steps with nothing to decide, stopping at the next point you
  actually have a choice.
- **↶ Zurücknehmen** (undo) rewinds the last action.
- **⟲ Neu starten** (restart) resets all the way back to a fresh
  mulligan.
- **⬇ Als Replay speichern** (save as replay) exports the current board
  position as a file you can re-open in Puzzle/Replay mode (see
  chapter 5) — handy for freezing an interesting spot to experiment
  with.
- **Beenden** (quit) ends the session and shows a summary screen.

## End-of-game summary

Whether you quit or the game actually ends (someone hits 0 life, and
so on), you get a stats digest per player: cards drawn/played, spells
cast, lands played, mana produced, average mana value, and damage
dealt/taken — plus a small bar chart of the mana curve of what was
actually cast and mana produced per turn. **Neues Spiel** (new game)
takes you back to the deck picker.
