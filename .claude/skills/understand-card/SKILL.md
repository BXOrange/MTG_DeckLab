---
name: understand-card
description: Read a card in rules terms before touching the parser or engine — normalized text, per-clause parser verdict, the exact Comprehensive Rules passages + glossary definitions that govern each clause and keyword, and Scryfall's "Notes and Rules Information" (official rulings) with the CR rules each ruling cites resolved to passages. Use when you need to understand what a card actually does under the CR, decide which rules a new parser handler or engine mechanic must respect, or validate that the pipeline already handles a card the way the rules say. Ships understand_card.py (card / clause / check / term / rulings), which does the two-hop rules_wiki lookup for you, cross-checks parser coverage against what the binder produces (correctly passing a pure mana ability instead of flagging a false gap), sorts common/structural glossary terms out of the way of the ones that actually matter, and flags rulings that describe timing/layer subtleties or explain an UNCLAIMED clause. `card`/`check` take multiple names and `card --brief` gives a one-line-per-card triage for skimming a whole batch fast.
---

# Understanding a card, in rules terms

The first move in parser work, engine work, and mechanic validation is always
the same: take the oracle text apart, work out which Comprehensive Rules
govern each clause, and see how far the pipeline already gets. By hand that's
`normalize` → eyeball the segmenter → chase every `RULE <n>` and glossary term
through `docs/Reference/rules_wiki/`'s two-hop lookup. `understand_card.py`
collapses that.

This skill **only reads and explains**. It does not decide what a clause
means, and it is not a runtime check. Hand off:

- **which real cards a handler would unlock / did a regex regress** →
  `extend-parser` skill's `parser_probe.py`
- **does the bound ability actually behave at runtime** → `game-engine`
  skill's `engine_bench.py` (`inspect` / `play`)
- **assemble a hand-authored catalogue entry** → `hand-author-card` skill's
  `author_card.py`

`understand_card.py` answers what comes first: *what is this card in rules
terms, and how far does the pipeline already get?*

```bash
cd backend && source venv/bin/activate     # or use venv/bin/python directly
UC=../.claude/skills/understand-card/scripts/understand_card.py
```

## The commands

### `card "<name>" [name2 ...]` — the full reading

```bash
python $UC card "Questing Beast"
python $UC card "Wrenn and Six" --rules       # inline every CR passage (--lines N to size them)
python $UC card --brief "Card A" "Card B" "Card C"   # skim a batch fast
```

Takes **one or more** names — feed it a `parser_probe.py rank`/`blocked` list
straight and it prints each in turn (`=== name ===` separators between them),
instead of one invocation per card.

Prints, for a cached card:

- identity — type line, mana, cmc, whether it's registered in
  `card_catalogue`, and the parser coverage verdict
- **raw oracle text vs `normalize()` output** side by side — the normalized
  form is what the segmenter and handler regexes actually match, so it's the
  text to reason about and write patterns against
- **per-clause verdict** — every clause the gate saw, marked `CLAIMED
  <ability_kind> [effect types]` or `UNCLAIMED`. `UNCLAIMED` lines are exactly
  what keeps the card `UNMODELED`
- **keywords** — each with the RULE that defines it (`Flying → RULE 702.9`)
  and its shape; `--rules` inlines the passage
- **governing rules** — a merged, CR-ordered list built from the keywords
  plus every defined glossary term in the text. Structural terms that show up
  on nearly every card (`Card`, `Damage`, `Hand`, …) are sorted to a single
  trailing "+N common" line instead of interleaved with the 2-4 rules that
  actually matter for *this* card. `--rules` inlines every passage
- **rulings** — shown automatically if already cached; `--rulings` fetches
  them once from Scryfall. Each ruling is tagged if it cites a `RULE <n>`,
  describes a timing/layer subtlety, or shares vocabulary with an `UNCLAIMED`
  clause (i.e. it probably explains the clause the parser can't model)
- a pointer to where each layer gets modeled (handlers / catalogue / engine
  primitive) and the `engine_bench.py` command for a runtime look

**`--brief`** collapses all of that to one triage block per card — identity
line, `coverage`/`registered`/clause counts, notable rules, and any
`UNCLAIMED` clause text — for skimming a whole batch without paging through
the full reading for each one; drop it once a specific card needs the real
reading.

### `clause "<text>"` — plan a handler before a card exists

```bash
python $UC clause "Whenever a creature you control dies, draw a card." --rules
```

Same rules/glossary mapping for an arbitrary template string, plus the gate's
verdict on that clause **in isolation** (a synthetic 1/1 carries it). Use it
when scoping a new parser handler: it tells you which CR sections the handler
must respect and which glossary terms are load-bearing. Then go to
`parser_probe.py` `clause` / `blocked` for the handler-prefix diagnosis and
the real cards it would unlock.

### `check "<name>" [name2 ...]` — validation triage

```bash
python $UC check "Grist, the Hunger Tide"
python $UC check "Card A" "Card B"     # also takes multiple names
```

Binds the card to a real `GameObject` via `bind_from_catalogue` and lays three
layers side by side:

- **parser** — per-clause `parser OK` / `parser GAP`, plus the coverage verdict
- **binder** — which `GameObject` effect lists actually got populated
  (`spell_effects=1`, `triggered_abilities=2`, …)
- **rules** — the governing-rule set for the whole card

then a `PASS` / `GAP` verdict that flags the internal contradictions worth
knowing before you dig in: parser says `MODELED` but the binder produced
nothing (a missing `EffectSpec.type` in `EffectRegistry`, or keyword-only
specs); a registered catalogue card that binds nothing (broken factory);
`UNCLAIMED` clauses the engine will silently no-op. A pure mana ability (RULE
605, e.g. Llanowar Elves) correctly binds nothing — `check` knows this and
`PASS`es it with a note instead of a false `GAP`, rather than making you
re-derive that exemption every time. A `PASS` means parser and binder are
self-consistent — runtime behaviour still needs `engine_bench.py play` and a
real test.

Add `--rulings` and it also lists every ruling that describes timing / layer /
counting behaviour — the cases most likely to bind and parse fine yet still
resolve wrong. Each is a line item to reproduce with `engine_bench.py play`.

### `rulings "<name>"` — Scryfall's "Notes and Rules Information"

```bash
python $UC rulings "Humility" --rules       # inline each CR passage a ruling cites
python $UC rulings "Opalescence" --no-fetch # cache only, never touch the network
```

Every ruling for the card, and — the point of routing it through this skill —
each `RULE <n>` a ruling's prose cites (`"rule 509.1a"`, `"704"`, `"layer 4"`)
resolved to its CR line and, with `--rules`, its passage. Rulings that share
vocabulary with an `UNCLAIMED` clause are flagged: that ruling is usually the
plain-English spec for the clause the parser gave up on. Fetched once from
Scryfall (project User-Agent + rate limit), then cached under
`<CACHE_DIR>/rulings/<id>.json` — every later read is offline. Offline with no
cache: a one-line "unavailable" note, nothing else breaks.

### `term "<name>"` — one glossary definition

```bash
python $UC term "Deathtouch"
python $UC term "Any Target"
```

The two-hop glossary lookup in one shot: the term's CR definition, then the
full rule it cross-references. (`engine_bench.py rule <n>` is the equivalent
for a bare rule number.) A typo or near-miss name doesn't just dump a
substring-filtered slice of ~740 terms — it's ranked by closeness (substring
hits first, then closest match), so the term you meant is near the top of the
suggestion list instead of buried in it.

## How it works (so you can trust or distrust it)

- Card text and coverage come from `parse_oracle` — the same fail-closed gate
  the coverage report uses. `CLAIMED`/`UNCLAIMED` here == `MODELED`/`UNMODELED`
  contribution there.
- Keyword → RULE comes from `parser/oracle/catalogue/keywords.py`'s own
  `KeywordDef.rule` (RULE 702 catalogue), not a guess.
- Rule and glossary passages are read straight from the newest
  `docs/Reference/MagicCompRules*.txt` via `rules_wiki/rule_line_index.json`.
  If the index is stale, regenerate with `rules_wiki/build_wiki.py`.
- The glossary-term scan is a whole-word match against all ~740 defined terms.
  Common terms (`Card`, `Player`, `Damage`) will show up — that's noise you
  skim past, not a claim they're the interesting part.
- Rulings come from Scryfall's public API (`rulings_uri` on the card's raw
  object in `data/scryfall_raw.db`, else `/cards/<id>/rulings`), fetched with
  the `config.py` User-Agent and rate limit, then cached as JSON under
  `<CACHE_DIR>/rulings/`. The one network call in this skill; everything else
  is local. A ruling → `RULE <n>` mapping is a regex over the ruling's prose,
  so it catches explicit citations only — a ruling with no rule number still
  matters, read it.
- **Coverage counts claims, not correctness.** A `CLAIMED` clause can still be
  modeled wrong — and a ruling is often where you find out how. Spot-check
  with `engine_bench.py`.

## Reference

`reference/rules-map.md` — a compact "oracle-text idiom → CR section → which
file models it" cheat-sheet, for the mapping the term scan can't make (idioms,
not single words).
