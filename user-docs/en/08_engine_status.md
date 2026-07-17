# 8. Engine Status

The **Engine-Status** tab isn't something you interact with — it's a
**transparency page** listing what the rules engine actually supports
today, and what's still missing, organized by feature area (turn
structure, combat keywords, static abilities, activated/triggered
abilities, card types, and so on).

Each line item carries one of three markers:

- **✅ Vollständig** (complete) — implemented and tested.
- **◐ Teilweise** (partial) — the common case works, with documented
  limits.
- **✖ Geplant** (planned) — designed for, but not built yet.

## Why it's useful

Goldfisch and Puzzle/Replay run against a genuine rules engine, not a
simplified mock — but that engine, like any implementation of a game
as complex as Magic, has edges it doesn't cover yet. If a card does
something unexpected (an ability seems to do nothing, or a keyword
doesn't seem to apply), this tab is the first place to check: it tells
you honestly whether that specific mechanic is modeled yet, rather
than leaving you to guess whether you hit a bug or an intentional gap.

It's kept up to date by hand alongside the engine itself, so treat it
as the authoritative answer to "does this app actually support X" for
any rules question that comes up while you're playing.
