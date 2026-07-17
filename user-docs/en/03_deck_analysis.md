# 3. Deck Analysis

Open a deck's analysis via **Decks verwalten** (manage decks) →
**Deck analysieren** (analyze deck) on the deck's row. The tab shows
three sub-tabs: **Statische Analyse**, **Dynamische Analyse**, and
**Bracket-Analyse**.

Everything here is computed **locally in your browser** from the
deck's card data — there is no AI/LLM call involved, and no new
network request beyond fetching card data. The classifications
(mana rock, fetchland, board wipe, and so on) are pattern-matching
heuristics over each card's rules text, not an official or verified
categorization — an unusually worded card can occasionally be
mislabeled or missed.

## Statische Analyse (static analysis)

A purely numeric breakdown, with a jump-to-section table of contents.
It does **not** judge card quality, synergy, or archetype — that's
what "Dynamische Analyse" is for (see below).

- **Summary tiles**: tutor count, number of lands (and % of the deck),
  average mana value with/without lands, total mana value, and
  detected "accelerant" count (mana rocks + dorks + land ramp).
- **Manakurve** (mana curve): a bar chart plus table of nonland cards
  by mana value.
- **Erwartete verfügbare Mana pro Zug** (expected available mana per
  turn): a line chart estimating how much mana you'll have on each
  turn, based on your deck's actual land count (adjusted for
  fetchlands' deck-thinning effect) — capped at one land played per
  turn. Three lines are shown: lands only, lands + accelerants
  ("realistic" — i.e. how many accelerants you'd statistically have
  drawn by then), and lands + accelerants ("maximum" — the best case
  if every accelerant were cast the instant it's affordable). This is
  a simplified estimate, not a full simulation.
- **Kartentyp-Verteilung** (card type distribution): counts by type
  (creature, land, artifact, instant, etc. — a card with two types
  counts in both bars).
- **Land-Archetypen** (land archetypes): lands are sorted into
  recognized cycles — basic, fetch, shock, pain, check, fast, slow,
  battle, triome, bounce (Karoo), horizon/canopy, manland, MDFC
  (modal double-faced spell//land cards), utility, or an unrecognized
  catch-all.
- **Manasymbole: Kartenbedarf vs. Manaquellen** (color pips: card
  requirements vs. mana sources): per color, how many colored mana
  symbols your cards need versus how many sources (lands, rocks,
  dorks) can produce that color.
- **Starthand & Landziehungen** (opening hand & land draws): the
  hypergeometric probability of drawing exactly *k* lands in your
  opening 7-card hand, plus a table of expected lands over time
  (accounting for the extra land a fetchland effectively finds).
- **Erkannte Beschleuniger** (detected accelerants): the actual card
  lists behind the ramp numbers above — mana rocks, mana dorks,
  land-enchanting auras, land-tutor ramp spells, plus rituals and
  Treasure-generators shown for reference (these two don't count
  toward the recurring-mana totals, since a ritual is a one-time burst
  and a Treasure token is consumed on use).
- **Funktionale Kategorien** (functional categories): every nonland
  card sorted into one Command-Zone-style bucket — Ramp, Card
  Advantage, Targeted Disruption, Mass Disruption, or Plan Cards (the
  rest) — with sub-breakdowns (e.g. Targeted Disruption splits into
  counterspells, removal, bounce, etc.) and a separate tutor list
  (tutors cut across categories, so they're not their own bucket).

## Dynamische Analyse (dynamic analysis)

Not implemented yet. This is meant to eventually judge a deck's
strategy, archetype, synergy, and overall coherence — for now the tab
just says so.

## Bracket-Analyse (bracket analysis)

An **unofficial heuristic approximation** of Wizards of the Coast's
"Commander Brackets" system — a 5-tier scale (1 Exhibition … 5 cEDH)
meant to set power-level expectations before a game. This is **not an
authoritative ruling**, just a rough estimate.

Of the criteria that distinguish brackets, only three can even
theoretically be read off a decklist, and this tab checks exactly
those three:

- **Game Changers** — cards on WotC's official Game Changers list (not
  allowed at all in Brackets 1–2, up to 3 in Bracket 3, unlimited in
  4–5).
- **Mass Land Denial** — effects that deny everyone's lands (not
  intended below Bracket 4).
- **Extra-Turn-Karten** (extra turn cards) — shown as a raw count for
  you to judge; a single one is fine, repeated/looped ones are not
  intended below Bracket 4.

Two other official criteria simply can't be checked this way: **two-card
infinite combos** need cross-card interaction knowledge no single-card
heuristic has (use a tool like Commander Spellbook for that), and
tutors stopped being a bracket criterion in WotC's October 2025 update.

The tab shows a suggested **minimum bracket** with its reasoning, plus
the actual cards behind each signal. Absence of a signal never proves
a deck belongs in bracket 1–3 — only bracket-tuning intent (not
checkable from a list) actually separates those three.
