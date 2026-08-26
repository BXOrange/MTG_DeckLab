---
name: hand-author-card
description: Hand-author a card's abilities into backend/mtg_analyzer/game/ability_catalogue.py — fast. Use when a card needs a catalogue entry (a replacement effect, a triggered ability with a real conditional predicate, or any card the oracle-text parser can't fully claim) rather than a parser handler. Ships author_card.py, which pulls the card's real oracle text, shows what the parser already claims (copy that part instead of re-deriving it), finds an existing catalogue entry with the closest shape to adapt, and assembles a paste-ready factory function + register() call + test skeleton in one command.
---

# Hand-authoring a card, fast

`game/ability_catalogue.py` is ~12k lines, one factory function per card. The
full field reference is
[docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](../../../docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)
— read it once for the `AbilitySpec`/`EffectSpec` whitelist (§4-§10); this
skill doesn't repeat that table, it exists to cut the *mechanical* cost
around it: finding the card's real text, discovering how much of it the
parser already parses for free, finding a template to copy, and assembling
the boilerplate.

```bash
cd backend && source venv/bin/activate
AUTHOR=../.claude/skills/hand-author-card/scripts/author_card.py
```

## 0. Should this even be hand-authored?

Per the guide's §1: only when `parse_oracle` can't fully claim the card, the
ability is a **replacement effect** (no parser grammar yet at all), it needs
a **real conditional trigger predicate** ("whenever you gain life", not just
"whenever ~ enters"), or you're prototyping a new `EffectSpec` type. If a
plain oracle-text handler would cover this card *and* a dozen others with the
same template, that's `extend-parser` skill work instead — a handler fixes
every card with that shape, a catalogue entry fixes one.

```bash
python $AUTHOR text "Card Name"
```

prints the real oracle text (as a Python literal — line breaks preserved,
paste straight into `raw_text=`/the docstring per the guide's §3 rule),
whether it's already registered, the parser's coverage verdict, and — the
useful part — exactly which clauses the parser can't claim. If `unclaimed`
is empty, stop: the card is already `MODELED`, no entry needed.

## 1. Don't re-derive what the parser already got right

```bash
python $AUTHOR reuse "Card Name"
```

Prints every clause the parser *did* claim as ready-to-paste `AbilitySpec(...)`
Python source — `EventType` symbols resolved, params intact. A card that's
"blocked" on one replacement-effect clause usually has two or three other,
perfectly ordinary clauses (an ETB draw, a static anthem) that the parser
already modeled correctly; copy those instead of rewriting them, and only
hand-write the clause that actually needed a human.

## 2. Find a template with the same shape

```bash
python $AUTHOR similar "Card Name"                    # by cached name
python $AUTHOR similar "Sacrifice ~ unless you pay {1}."   # by raw clause text
python $AUTHOR check "Riot Control"                    # read one candidate's full source
```

`similar` ranks every existing catalogue entry by textual closeness to the
query (scored against each entry's own quoted-oracle-text preview, not its
design-commentary tail) — the fastest way to find a replacement effect,
quoted-ability grant, or per-firing marker shaped like the one you need,
since those idioms are much easier to adapt than to invent from the field
reference alone. `check` prints one entry's full source plus every alias
name it's registered under (reprints), so you can see immediately whether
it's close enough to copy.

## 3. Assemble the scaffold

```bash
python $AUTHOR scaffold "Card Name"
```

One paste-ready block: the factory function (docstring = real oracle text,
parser-claimed clauses pre-filled via the same rendering as `reuse`, a
`# TODO` + a stub `AbilitySpec("???", ...)` per unclaimed clause naming the
exact raw text you still need to model), the `register(...)` call, and a
matching test skeleton for `backend/tests/test_ability_catalogue.py` — the
`ability_kind` assertion and the `obj.<list>` bind-check are filled in from
the kinds actually detected, not left as a guess. Refuses to run (and prints
the existing entry instead) if the card is already registered.

Fill in the TODOs using the guide's §5 (`EffectSpec` whitelist), §6 (static/
layers), §7 (replacement), §8 (triggers, incl. the conditional-predicate
escape hatch), §9 (costs) — then paste the whole block into
`ability_catalogue.py` at a reasonable spot (alphabetical isn't enforced,
just don't split a card's own entry from its `register()` call).

## 4. Validate against the real engine

This skill only ever reads; it never touches `ability_catalogue.py` or
`game/`. Once you've pasted the scaffold in, use the **game-engine** skill's
`engine_bench.py` for everything runtime:

```bash
BENCH=../.claude/skills/game-engine/scripts/engine_bench.py
python $BENCH inspect "Card Name"      # bound abilities, layer output, legal actions
python $BENCH play "Card Name"         # cast/resolve it for real, full event trace
python $BENCH primitives 'shape'       # confirm an EffectSpec type before inventing one
```

`inspect` showing nothing bound after you've registered the card means the
`EffectSpec.type` string isn't in `EffectRegistry` (a typo, or a type that
genuinely doesn't exist yet — see the guide's §15 before adding one).

## 5. Tests, then close the loop

Follow the guide's §13 checklist: `specs_for` returns the right kinds, twice
returns non-identical objects, `bind_from_catalogue` populates the right
`GameObject` list, and a real end-to-end test resolves the ability and
asserts the board changed — not just that an object was constructed.

```bash
python -m pytest -q
```

- [ ] Register every alias name a functionally-identical reprint uses (guide
      §14 — `Evolving Wilds`/`Terramorphic Expanse` is the pattern; `check`
      on a card's canonical name shows you every alias an existing entry
      already carries).
- [ ] If this card closes a `BACKLOG.md` ticket: **delete** the ticket, don't
      tick it, and append the narrative to `Done_Backend.md`.
- [ ] Commits only when asked; branch first if on `main`.

## Hard rules (from the guide, worth repeating)

- **Return fresh objects every call.** Never hoist the returned list to a
  module constant — the binder mutates specs when binding, and two
  permanents of the same card must never share one instance.
- **Preserve line breaks in quoted oracle text.** `\n` is the ability-block
  boundary; joining lines into one sentence erases it. `text`/`reuse`/
  `scaffold` all emit `repr(oracle_text)` for exactly this reason — paste
  that, don't retype the text by hand.
- **Nothing derived from card text becomes code.** `EffectSpec.type` must
  already exist in `EffectRegistry`/`ReplacementRegistry` — the catalogue is
  trusted *content*, never trusted *code*. A new type is a `game/effects.py`
  change (guide §15), not something a catalogue entry can freehand.
- **A registered card gets the parser turned off entirely for it** — once
  you register a name, `specs_for` never falls back to `parse_oracle` for
  it, so the hand-authored entry must cover *every* ability the card has,
  including the ones the parser already got right (§1 above is precisely
  why `reuse` exists).
