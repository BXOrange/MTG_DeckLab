# 6. Settings, Profile & Card Art

Two header icon buttons split the old single settings screen in two:

- **Einstellungen** (settings) — *only* how this browser reaches the
  backend server.
- **Profil** (profile) — everything about *you*: your player name, your
  multiplayer preferences, and any custom art you've uploaded.

The rule of thumb: *reaching the server* is Einstellungen, *who you are
and how you play* is Profil.

## Einstellungen: server address

- **Server-Adresse** (server address) — where the backend lives (e.g.
  `http://localhost:8000`).

Click **Speichern** (save) to store it. It's kept in a **browser
cookie**, not on the server, so it only applies on this browser/
device; a different browser or computer starts from defaults again.
**Verbindung testen** (test connection) re-checks reachability on
demand; the same status also shows live in the page header.

## Einstellungen: refreshing local data

Under **Lokale Daten** (local data), you can manually refresh the full
Scryfall card pool and the Commander Spellbook combo database. Otherwise
the combo database is downloaded only when the first static deck
analysis needs it. Both data sets are stored server-side in SQLite; the
combo update reports how many variants were added, changed, or removed.

## Profil: player name

- **Spielername** (player name) — free text, no account or password
  behind it. It's how your uploaded token art, card sleeves and
  favorite decks (below) are filed on the server, so that in a
  multiplayer game an opponent on the same server could see your art
  too.

Click **Speichern** (save) to store it — also a browser cookie, per
device. Saving also mints this browser a hidden identity token (90
days, renewed on every save) so a second browser using the same name
doesn't claim your seat at a multiplayer table.

## Profil: multiplayer default settings

**Mehrspieler: Standardeinstellungen** (multiplayer defaults) — format,
seat count, mulligan rule, take-backs per player, and the RULE
103.1/103.2 randomization toggles. These are applied automatically to a
table *you* open (in the **Multiplayer** tab); at the table itself the
host can still change them.

## Profil: auto-pass & board comfort

**Mehrspieler: Auto-Pass** and **Mehrspieler: Spielfeld** — this
browser's own play-comfort toggles (auto-pass on/off, its countdown
seconds, whether it also runs on your own turns, "pass immediately when
there's nothing to do", and whether an opponent's hand is drawn as
face-down cards or just a count). All of these are *also* adjustable
directly on the board mid-game. See chapter 9 for what they do.

## Profil: custom token art

Some tokens an effect creates mid-game have no real Magic card behind
them (a plain "1/1 white Soldier", for instance) and so no official
art. Under **Eigene Token-Bilder** (custom token images) you can
upload your own image for:

- A specific **known token type**, picked from a dropdown (populated
  from the app's token catalogue) — e.g. a particular named token your
  decks actually produce.
- **Andere …** (other) — type any custom token name by hand if it's
  not in that list.
- **Generisch (alle Token ohne eigenes Bild)** (generic — all tokens
  without their own image) — a catch-all fallback shown for *any*
  token that has neither real art nor a specific upload of its own.

This requires a saved player name first. Uploaded images appear in a
grid below the form, each with a **Löschen** (delete) button.

## Profil: card sleeves

Under **Karten-Sleeves** you can upload custom card-back designs, each
with a label. Once uploaded, assign one to a specific saved deck from
its row's sleeve dropdown in the **Decks verwalten** (manage decks)
tab.

A deck's sleeve is used as fallback art for a face-down or transformed
*token* with no art of its own on the game board — it has no visible
effect on a real double-faced card (those show their genuine printed
back), since there's currently no modeled face-down state (like
morph) that would actually need it. Consider it groundwork for later
rather than something you'll see change much today.

## Profil: favorite decks

Under **Lieblingsdecks** (favorite decks) you can star a subset of your
saved decks. Starred decks are listed first in the deck pickers in the
Goldfisch mode and the multiplayer lobby.
