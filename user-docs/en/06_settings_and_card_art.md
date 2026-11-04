# 6. Settings, Profile & Card Art

Two header icon buttons split the old single settings screen in two:

- **Einstellungen** (settings) — server connection, local data and
  MCP setup.
- **Profil** (profile) — everything about *you*: your account (sign-in, sessions,
  password), your multiplayer preferences, and any custom art you've uploaded.

The rule of thumb: *reaching the server* is Einstellungen, *who you are
and how you play* is Profil.

## Settings: server connection

Under **Settings → Board**, set **Bot speed** to **Instant**, **Normal** or
**Slow**. It controls the delay between displayed bot actions, is saved locally
and applies immediately to all game views.

The app automatically uses the address where you opened it. There is no
server-address field or saved address override; old address cookies are
ignored. **Verbindung testen** (test connection) re-checks reachability.
The same status appears in the page header.

## Einstellungen: refreshing local data

Refreshing the full Scryfall card pool and the Commander Spellbook combo
database is done by the server administrator on the `/admin` page of the
server machine, not by players. (The old update buttons under **Lokale
Daten** are gone.) Otherwise
the combo database is downloaded only when the first static deck
analysis needs it. Both data sets are stored server-side in SQLite; the
combo update reports how many variants were added, changed, or removed.

## Profil: the five tabs

The profile has five tabs: **Account-Login**, **Sessions/Einladungen**
(sessions/invitations), **Passwort ändern** (change password),
**Multiplayer-Einstellungen** (multiplayer settings) and
**Sleeves/Token-Bilder** (sleeves/token images, including favorite
decks). While you are signed out only *Account-Login* is usable (sign
in, create an account with an invitation, "Passwort vergessen"); the
other tabs are greyed out and unlock when you sign in. The tab you used
last is remembered in this browser.

There is no free-text player name: games show your **account name**,
and without a login your seat is called **"Player"**. Your uploaded
token art, card sleeves and favorite decks belong to your account;
other players cannot see or change them.

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

This requires being signed in. Uploaded images appear in a
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

## Bug reports

Click the bug icon beside Settings to describe a problem. During a game, the
report includes the current Replay and the last 12 actions by default; you can
change that number. Compressed JSON reports (`.json.gz`) are saved on the backend in the local,
unversioned `bug-reports/` folder. A report outside a game contains only the
description and view context. The dialog confirms the saved filename.
