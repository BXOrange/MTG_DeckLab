# 7. Card Cache

The **Karten-Cache** (card cache) tab is a simple browsing view — it
shows every card the app has ever looked up and cached, as a grid of
card-art tiles with their details.

There's nothing to configure here: cards are added to the cache
automatically whenever a decklist mentions them (in "Deck editieren"
or elsewhere), so the list grows on its own as you use the app.

- The tab loads its list the first time you open it in a session (not
  eagerly at startup).
- **Aktualisieren** (refresh) re-fetches the list — useful if you've
  just imported a deck with new cards elsewhere and want to see them
  show up here too.

If the tab shows "Noch keine Karten im Cache" (no cards cached yet),
import a decklist first.
