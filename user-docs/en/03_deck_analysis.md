# 3. Deck Analysis

Open a deck's analysis via **Decks verwalten** (manage decks) →
**Deck analysieren** (analyze deck) on the deck's row. The tab shows
four sub-tabs: **Static analysis**, **Dynamic analysis**,
**Bracket analysis**, and **Advice**.

Everything except combo matching is computed **locally in your
browser** from the deck's card data — there is no AI/LLM call involved.
The combo list is matched by the backend against a local Commander
Spellbook snapshot, fetched lazily on first use and stored in SQLite.
The classifications
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
  turn, based on the exact expected number of land drops from your
  opening hand and draws; fetchlands are cracked when played and
  assumed to find a land if one remains in the library. Three lines
  are shown: lands only, lands + accelerants
  ("realistic" — the reproducible mean over 8,192 shuffled opening
  hands and draw sequences), and lands + accelerants ("maximum" — favorable draws and
  affordability). Recognized lands use their actual output (e.g. Ancient
  Tomb produces two mana); mana-rock activation costs (e.g. a Signet's
  generic mana cost) are subtracted. Mana rocks can be used the turn
  they are cast; mana dorks produce starting on the next turn. The
  maximum curve also limits accelerants to hand slots remaining after
  land drops. This is
  a simplified estimate, not a full simulation; mana is an expected
  value, not the probability of being able to pay a particular card's cost.
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
- **Commander Spellbook combos**: listed variants whose cards are
  present in the deck. On first use the server downloads the compressed
  full snapshot from Commander Spellbook; later analyses use the local
  SQLite database. Cards are matched by exact name. Additional template
  requirements are shown but not checked against the deck, so those
  variants do not affect the bracket estimate.

## Dynamische Analyse (dynamic analysis)

Not implemented yet. This is meant to eventually judge a deck's
strategy, archetype, synergy, and overall coherence — for now the tab
just says so.

## Bracket-Analyse (bracket analysis)

An **unofficial heuristic approximation** of Wizards of the Coast's
"Commander Brackets" system — a 5-tier scale (1 Exhibition … 5 cEDH)
meant to set power-level expectations before a game. This is **not an
authoritative ruling**, just a rough estimate.

Not every criterion that distinguishes brackets can be read from a
decklist. This tab checks the following signals:

- **Game Changers** — cards on WotC's official Game Changers list (not
  allowed at all in Brackets 1–2, up to 3 in Bracket 3, unlimited in
  4–5).
- **Mass Land Denial** — effects that deny everyone's lands (not
  intended below Bracket 4).
- **Extra-Turn-Karten** (extra turn cards) — shown as a raw count for
  you to judge; a single one is fine, repeated/looped ones are not
  intended below Bracket 4.

Two-card infinite combos are derived from Commander Spellbook variants
whose listed outputs explicitly contain "Infinite". Variants with
unverified template requirements are excluded. To estimate when the
combo's pieces can be cast, the app pays each card's mana value from the
maximum mana curve turn by turn. Pieces may be cast over multiple turns;
unused mana does not carry forward, and mana spent on ramp is not counted
again for combo cards. If all pieces can be cast by turn 6, the combo
counts as early (suggested minimum Bracket 4); later combos count as a
Bracket 3 signal. This assumes every combo card is available and does not
simulate a specific combo hand, colors, or actual game states; it uses
expected land drops as a mana budget. It is a
project heuristic, not an official numeric WotC definition of "early".
Tutors stopped being a bracket criterion in WotC's October 2025 update.

The tab shows a suggested **minimum bracket** with its reasoning, plus
the actual cards behind each signal. Absence of a signal never proves
a deck belongs in bracket 1–3 — only bracket-tuning intent (not
checkable from a list) actually separates those three.

## Advice

The Advice sub-tab compares the deck's mana curve with Frank Karsten's
Commander reference model from the [TCGplayer guide](https://www.tcgplayer.com/content/article/What-s-an-Optimal-Mana-Curve-and-Land-Ramp-Count-for-Commander/e22caad1-b04b-4f8a-951b-a41e9f08da14/).
For commander mana values 2–6 it shows the guide's sample spell counts,
mana-rock counts, and land count alongside the deck's detected counts.
The reference curve can be switched between a table and a bar chart. The
mana-base section gives the model's land and rock targets and how far
the deck's effective land and rock counts differ from them.
The guide favors a mix of two-, three-, and four-mana spells, a somewhat
thinner slot at the commander's own mana value, and generally more lands
than many common templates suggest. Its simplified model is a reference,
not a prescription; synergy and the deck's actual plan can justify
deviations.

Land guidance treats modal double-faced spell/land cards as half a land.
It compares the deck's effective land and rock counts with the
commander-specific reference numbers where available, and shows the
guide's rough 37-land floor and 42-land-plus-Sol-Ring general starting
point. Outside the commander-specific models, it estimates a land range
from the guide's rock-to-land tradeoff when Sol Ring is present.
These are approximate targets, not rules. Colored-source flags
reuse the static analysis's heuristic counts; they do not account for
availability, tapped lands, or exact mana costs.

The separate **Empirical land estimate and ramp consistency** comparison
uses Karsten's published 2022 formula: 31.42 + 3.13 × average nonland mana
value − 0.28 × cheap draw/ramp count. It excludes the commander from the
average. Cheap normally means mana value at most two, with one-mana cycling
also qualifying. Cards count once. The ordinary-land target subtracts the
published MDFC credit (0.38 non-mythic / 0.74 mythic) and rounds the result.
Missing MDFC rarity withholds that target. This is an approximate 99-card
reference derived from 60-card tournament data, not a deck-specific optimum.

The ramp table shows exact odds of drawing at least one recognized early
ramp card, plus joint land/ramp draw odds. Select a 70%, 80% or 90% reliability
preference to see the early-ramp count needed by turn 2, and set explicit
opening-hand land/ramp requirements. These probabilities use your actual
library size, assume no mulligans or extra draw, and include the turn-one draw.
They measure cards drawn, not available colored mana or successfully cast
ramp. MDFCs are excluded from probability land/ramp categories. Early ramp
uses a narrower definition than the regression; both input lists and the
limitations are available under **Inputs, assumptions and sources**.

The Combo database section suggests missing fixed card ingredients from
Commander Spellbook variants that share at least one card with the deck.
Recommendations are drawn from the local Spellbook snapshot and do not
verify template requirements or prove the combo is playable. Combo
recommendations are not used to change the Bracket estimate.
