# 2. Deck Import & Saved Decks

## Entering a decklist ("Deck editieren")

This tab has three separate text boxes, and which box you paste a card
into is what decides its role — there's no need to type section
headers:

- **Commander**
- **Mainboard** (Hauptdeck)
- **Sideboard**

Each line is one card, in either of these formats:

- `1 Sol Ring`
- `4x Mountain`

A set code and collector number, as in `1 Ancient Tomb (V12) 1 *F*`, select
the artwork for that printing when you parse the list. Finish markers such as
`*F*`, `*E*`, `★` and `☆` are ignored when matching names. Lines starting
with `#` or `//` are comments.

Click **Deckliste parsen** (parse decklist) to read the three boxes.

After parsing, click **Artwork** next to a card in the list on the right.
Choose a printing or restore the default artwork. **Update** or **Save as new**
saves your choices for that deck. Each choice applies to every copy of that
card in the deck and is used in analysis and in games.

## What the result panel shows

After parsing, you get:

- A total card count and a **Legal (strukturell)** / **Nicht legal**
  status badge, based on structural Commander rules: exactly 100 cards
  total (including the commander), singleton (only basic lands may
  repeat), and one commander (two if it's a partner pair).
- Any parse errors (a line that couldn't be read) or validation
  warnings/errors.
- The Commander, Hauptdeck (mainboard), and Sideboard lists themselves.

A moment after parsing, the same list is re-checked **server-side**
against the app's real card database. This adds:

- 🛑 markers on any card name the server couldn't resolve at all (check
  the spelling).
- ❗ markers on cards that are resolvable but not actually legal for
  this commander — banned on the Commander ban list, or outside the
  commander's color identity. Hover over a marked card to see which.
- A "Serverseitig geprüft" (server-checked) confirmation once this
  finishes.

Check the **Detailansicht (Bilder & Eigenschaften)** (detail view:
images & properties) checkbox to switch the card lists from plain text
rows to a grid of card-art tiles.

## Saving a deck

Give it a name in the **Deckname (zum Speichern)** field, then choose:

- **Aktualisieren** (update) — overwrites the deck you currently have
  loaded. Only enabled once a deck has actually been loaded or saved
  once already.
- **Als neues speichern** (save as new) — always creates a brand-new
  saved deck, leaving whatever you had loaded untouched, and then
  switches to point at the new copy.

These are deliberately two separate buttons rather than one "Save" —
so that editing a loaded deck's commander, for instance, can't
silently overwrite the original by accident.

Once the deck has passed the server-side check, a **Zum
Goldfisch-Modus →** (to goldfish mode) button appears at the bottom of
the result panel to jump straight into playing it.

## Managing saved decks ("Decks verwalten")

This tab lists every deck you've saved, each row showing:

- Its name, commander (👑, if any), color-identity pips (WUBRG, or "C"
  for colorless), and save timestamp.
- A legality badge: **✅ legal** or **🛑 nicht legal** (hover for the
  reasons) — checked server-side, same rules as above.
- A **sleeve dropdown** — pick a custom card-back design for this deck
  (see chapter 6 for uploading sleeves); "Kein Sleeve" (no sleeve) is
  the default.
- **Deck editieren** — loads it back into the "Deck editieren" tab.
- **Deck analysieren** — opens it in the "Deck analysieren" tab (see
  chapter 3).
- **Löschen** (delete) — asks for confirmation, then removes it for
  good.

Use **Aktualisieren** at the top of the tab to refresh the list (e.g.
after saving a new deck elsewhere).
