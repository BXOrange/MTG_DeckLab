# 6. Settings & Card Art

The **Einstellungen** (settings) tab covers your connection to the
backend server and any custom art you've uploaded.

## Player name & server address

- **Spielername** (player name) — free text, no account or password
  behind it. It's just how your uploaded token art and card sleeves
  (below) are filed on the server, so that in a future multiplayer
  game an opponent on the same server could see them too.
- **Server-Adresse** (server address) — where the backend lives (e.g.
  `http://localhost:8000`).

Click **Speichern** (save) to store both — they're kept in a **browser
cookie**, not on the server, so they only apply on this browser/
device; a different browser or computer starts from defaults again.
**Verbindung testen** (test connection) re-checks reachability on
demand; the same status also shows live in the page header.

## Custom token art

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

## Card sleeves

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
