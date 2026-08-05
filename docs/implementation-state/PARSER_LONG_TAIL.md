# Oracle parser: the long tail — strategy & worked examples

The **examples** document of the three-way split (see
[BACKLOG.md](BACKLOG.md) for open tickets, `Done_*.md` for worklogs). Nothing
here is a ticket to close; it is the standing method for the indefinite part
of parser coverage, plus enumerated samples that calibrate how that tail
actually behaves.

Tracked in the backlog as a single standing entry, `PAR-12`.

## Where coverage stands

Measured by `scripts/coverage_report.py` (ledger-backed via
`services/coverage_db.py`), against the full ~34k-card Oracle universe:

**29.7% covered — 10,151 / 34,208 — as of 2026-08-05, PARSER_VERSION 57.**

"Covered" = parser-`MODELED` **or** hand-`AUTHORED`. Re-run the report rather
than trusting a figure quoted here, in `CLAUDE.md`, or in the Engine-Status
tab; after any change here, sync all three.

**Bump `PARSER_VERSION` (`parser/oracle/gate.py`) in the same session you add
a handler.** The ledger is keyed on content-hash **+ version**, so measuring
twice within one batch (bump, measure, add more handlers, measure again)
silently reuses the first run's rows. Either bump again or delete that
version's rows. Hand-authoring alone needs no bump — `content_hash` folds in
`ability_catalogue.is_registered`.

## How the tail gets closed

The remaining ~25k templates are, by construction, not generic. This is an
*indefinite program*, not a finite batch list, and proceeds two ways:

1. **Narrow parser extensions** for singleton shapes that still generalize a
   little — a slightly different targeting scope, a compound filter.
   Preferred: each still pays off across a small cluster.
2. **Hand-authoring** genuinely unique cards in `game/ability_catalogue.py`
   ([authoring guide](../Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)),
   only after confirming no near-miss handler would unlock a cluster.

Deterministic-first: classification, scaffolding and measurement are pure
code, no LLM. LLM/subagent effort (Sonnet/Haiku only, file-ownership waves)
goes only to finalizing a handler's regex/builder semantics and to
hand-authoring the tail.

A few items are deliberate non-goals — the legacy pre-2021 werewolf
template, silver-border/acorn/un-set cards — excluded from the denominator or
accepted as permanently unmodeled. Stickers and Attractions are project
non-goals tracked in [BACKLOG.md](BACKLOG.md) under MEC.

## Two tracks: basic mechanics vs. set-specific mechanics

The tail isn't one undifferentiated pile — every unclaimed template falls
into one of two tracks, and they get worked by two different prioritization
rules, not one:

- **Basic mechanics** — an oracle-text *shape*, keyword-action, or template
  that recurs across many sets and years (a modal wrapper, a P/T
  characteristic-defining ability, an O-Ring variant, a targeted-destroy
  compound, or a keyword *action* like Investigate/Explore/Scry that a
  design team keeps reprinting set after set once it exists). Worked by raw
  cache-wide yield (`parser_probe.py rank`/`blocked`) — a fix here keeps
  paying off on sets not yet printed, so the biggest SOLO count wins
  regardless of which deck happens to need it today. This is the default
  track and where most of this document's worked examples live.
- **Set-specific mechanics** — a RULE 702 keyword *ability* or *action*
  that a design team built for, and largely confined to, **one expansion or
  Commander-precon product line** (it may get one or two nostalgia reprints
  years later, but no ongoing set keeps printing new cards with it). A fix
  here only pays off for decks actually built around that product — so it's
  worked **deck-first**: when auditing a saved deck whose commander (or the
  deck itself) comes from a named set/precon, check that set's own
  signature mechanic(s) against the table below *before* falling back to
  generic cache-wide ranking, since a single precon commonly clusters a
  dozen+ of its own set's cards into one saved deck.

  A mechanic only belongs in this table once someone has actually run
  `parser_probe.py blocked "<its regex>"` and confirmed real cards are
  blocked on it — a name alone (guessed from a set's marketing copy) isn't
  worth an entry; verify, then add the row. Extend this table as each
  deck's audit turns up its set's mechanic, rather than trying to
  pre-populate every named product's keyword in one pass.

  | Mechanic | RULE | Set / product | Status (as of date checked) |
  | --- | --- | --- | --- |
  | The Ring tempts you | 701.51/701.52 | Tales of Middle-earth | **Done** — `Player.ring_level`/`ring_bearer_id` (`Done_Backend.md`, cEDH-cube batch); the oracle-text clause itself and "whenever the Ring tempts you, `<effect>`" (`EventType.RING_TEMPTED`) followed later (2026-08-05) |
  | The One Ring's own bespoke clauses (protection-from-everything-on-cast, burden-counter life loss, burden-counter draw scaling) | — | Tales of Middle-earth (one unique card) | **Partially done** (checked 2026-08-05) — "burden" is now a recognized named counter kind, but the card's other two clauses are still unclaimed; likely hand-authoring territory (RULE 122.1a's burden-counter card is a singleton, not a cluster) |
  | Frodo, Adventurous Hobbit (this deck's own commander) | — | Tales of Middle-earth | **Done** (2026-08-05) — `GameState.life_gained_this_turn` (new per-turn tracker) + `EffectSpec.condition`'s `"is_ring_bearer"`/`"ring_tempted_at_least"` keys, `effects.ConditionalEffect._condition_holds` generalized to AND multiple condition keys together. The same `"is_ring_bearer"` key also closed Aragorn, Company Leader/Faramir, Field Commander's "if you chose a creature other than ~" clause (each still has one unrelated second gap of its own) |
  | Frodo, Sauron's Bane (the same DFC's back face) | — | Tales of Middle-earth (one card) | **Not done** (checked 2026-08-05) — a bespoke "activated ability conditionally changes this permanent's own type/P·T" shape (RULE 205) unlike anything else cached; genuinely singleton, hand-authoring territory, not attempted |
  | Choose a Background | 702.124 | Commander Legends: Battle for Baldur's Gate | **Done** (2026-08-05) — bare FLAG keyword, inert in-game like Partner; the deckbuilding pairing check itself is [BACKLOG.md](BACKLOG.md)'s DB-3, still open |
  | Magecraft | ability word | Strixhaven | **Done** — `segmenter._MAGECRAFT_RE` |
  | Amass / Mutate / Monstrosity / Adapt / Goad / Bargain / Fading / Soulbond | 701.x / 702.x | War of the Spark / Ikoria / Theros / various | **Done** — see `Done_Backend.md`'s cEDH-cube batch |
  | Day/Night (werewolf transform) | 702.28 (2011+ template) | Innistrad: Midnight Hunt/Crimson Vow | **Done** — the *legacy* pre-2021 template is the one accepted non-goal above |
  | Specialize | ~702.166 | Duskmourn: House of Horror | **Not done** (checked 2026-08-05) — 50 SOLO cache-wide (`Gut, Bestial/Brutal Fanatic`-shaped); needs a real "the exiled card becomes a copy, sacrifice-timed token" effect, not yet built |
  | Starting intensity | Duskmourn's Room-adjacent template | Duskmourn: House of Horror | **Not done** (checked 2026-08-05) — 0 cards SOLO-blocked on the phrase alone (always paired with another unclaimed clause); needs its co-blocker identified before estimating real scope |
  | Learn (Lessons) | 701.50 | Dominaria / Strixhaven | **Partially done** (checked 2026-08-05) — bare "Learn." is a 7-card SOLO cluster; the Lesson-sideboard-zone infrastructure itself (RULE 701.50a "look at your sideboard") isn't built, so a full deck with real Lessons stays out of scope regardless |
  | Investigate | 701.19a | Shadows over Innistrad (**reused across many later sets** — belongs on the *basic* track, listed here only as the worked example that motivated this split) | **Done** (2026-08-05) — a `create_token` alias onto the already-shipped Clue token, 87+ cards in one row; this is the case study for "keyword action, but basic not set-specific" — check *reuse breadth* before filing something here |

  Doctor's companion / Time travel (Doctor Who), "Start your engines!"
  (Aetherdrift), Augment (Aether Revolt), "For Mirrodin!" (Mirrodin block),
  ki counters (Kamigawa block), and whatever Edge of Eternities/Lorwyn
  Eclipsed/New Capenna/Bloomburrow turn out to print as their own signature
  mechanic are all **known-unverified** — real cards are blocked on some of
  these phrases (see `rank`'s live output), but nobody has yet confirmed
  scope/primitive-existence for them the way the rows above were. Don't
  copy a status onto this list without running the check yourself.

## Lessons that keep recurring

Each was paid for once; re-reading them is cheaper than re-learning them.

- **A ranked template that is a block *wrapper* (modal, Saga, Class level) is
  usually a red herring.** `gate.py` fail-closes the whole block when any one
  mode body fails, appending *every* body to `unclaimed` — so the wrapper
  shows up in the ranking as a proxy for "some sibling clause still has a
  gap". Re-derive which sub-clause actually fails before trusting a
  template's face-value card count.
- **The all-or-nothing coverage gate makes every batch-plan estimate an
  overcount.** Most cards blocked by a template have *other* unclaimed
  clauses too. A family whose primitive is correct and tested can still
  yield literally zero newly-covered cards.
- **A plan-doc row's own framing can be wrong.** Escape/Kicker/Multikicker
  were documented as "new keyword mechanics" but were already fully modeled
  — the real blockers were two recognition bugs. Sample real cards before
  accepting a stated scope.
- **When a handler's regex has a subject alternation, check every
  alternative is actually read out.** `_lose_life` and later `_discard` both
  matched "target player …" but never threaded `target_kind` through, so
  both silently applied the effect to the source's controller instead.
- **When a general regex fix passes the happy path, write the adversarial
  "why doesn't this over-match" test before trusting it.** A general
  keyword-line split looked correct until `"flying, then draw a card"`
  caught it; it was replaced with a narrow closed list.
- **Parse-only tests aren't enough — write execute tests.** Two shipped
  effect families passed the whole suite yet crashed on first real use
  (`Zone` imported under `TYPE_CHECKING` only; `legal_targets` missing a
  branch and silently returning `[]`). Also: new selector params must be
  whitelisted in `effects._SELECTOR_KEYS`, or they are silently dropped.
- **A ticket that reads as "N more rows in a whitelist" is worth
  re-measuring before you write the rows.** MEC-14 listed four condition
  phrasings as four independent entries; the biggest of them turned out not
  to be a new *kind* at all but a new **subject** ("as long as *enchanted
  permanent* is a creature" is about the Aura's host, not the Aura), and one
  `of` key made every existing kind work on that subject for free. Two of
  the other three then needed no more than the row the ticket predicted. The
  general lesson: when several ticket items share a shape, look for the
  axis they vary along before adding one entry per item.
- **"Needs a new primitive" is worth re-checking against the phrasing.**
  MEC-14's soulbond item was blocked on nothing at all in the engine — the
  ``soulbond_pair`` selector had shipped with the cEDH cube batch and simply
  had no oracle phrase that could reach it. Three parser rows closed it.
  This is the same failure mode `CLAUDE.md`'s batch-discipline rule
  describes, seen from the other end.
- **Ticket card estimates are wrong in both directions, and the wrong
  *shape* is the expensive kind.** MEC-12(a) described a variable target
  count as "Death Kiss, 1 card". Death Kiss really is the only card with
  that phrasing — but four *other* cards print "for each opponent, goad up
  to one target creature that player controls", which is the same feature
  with an already-shipped constraint (`distinct_controllers`) doing the rest.
  Measuring the *mechanism* rather than the quoted phrase turned a
  one-card item into a five-card one at no extra cost.
- **"Coverage" and "actually playable" are two different claims — check
  both.** Three separate PAR-6..10 (2026-08-03) cards were already
  `MODELED` (the coverage gate satisfied) while being functionally inert: a
  bare Cycling keyword was claimed but bound to no real activated ability
  (PAR-9); a layer-6 grant reaching the *hand* zone populated
  `granted_activated_abilities` correctly, but `legal_actions`' hand-zone
  loop only ever scanned `activated_abilities`, so the granted one was
  never offered (PAR-8); and `can_activate` had no branch at all for an
  ability sourced from the *graveyard* zone, so a new "return this card
  from your graveyard to the battlefield" effect would have been unusable
  the moment it shipped (PAR-10). None of these show up in a coverage
  diff — only playing the card (or writing an execute-level test that
  calls `legal_actions`/`can_activate`, not just `bind_from_catalogue`)
  catches them. Grep for the *offering* code path, not just the binding
  one, whenever a new effect targets a zone/ability-list combination
  nothing has used yet.
- **A ticket's own example can be hiding a much bigger, unrelated family
  one clause away.** PAR-10 was framed as "Jin-Gitaxias's compound
  activation condition" (a handful of cards). Sizing its SOLO list turned
  up Dread Wanderer blocked on a *second*, wholly unrelated clause: "Return
  this card from your graveyard to the battlefield[, tapped]." was
  entirely unrecognized — 69+ cache cards, by far the batch's biggest win,
  found only by running `blocked` on the literal phrase inside a
  "ALSO BLOCKED" card's *other* unclaimed line rather than stopping once
  the ticket's own named clause was handled.

## Worked example: the battle pool (RULE 310)

The battle *card type* is fully implemented (see `Done_Backend.md`,
"Card-type & structural coverage"), which makes this pool a clean sample of
what the tail is actually made of: **12 of 39 cached battles are MODELED**,
and the other 27 fail on ordinary effect-body grammar with nothing to do with
battles as a type. Grouped by what each actually needs, most-cards-first:

- **"you may `<cost>`. If you do, `<effect>`."** — Occupation of Kulrath,
  Invasion of Mercadia, Invasion of Ergamon. **The engine primitive already
  exists**: `RulesEngine.request_pay_cost_then` (RULE 118.3, built for Mana
  Vault and the Pacts, with an "if you don't" branch). This is a *parser
  handler only*. Do not re-defer it as "needs a primitive" — highest-yield
  item here and the natural next one to take.
- **"search your library and/or graveyard"** — Invasion of Ikoria, Invasion
  of Arcavios (the latter also "outside the game"). Same blocker as the
  Doomsday/Finale entry; closing that closes these.
- **Multi-target "up to N target creatures each get …"** — Invasion of
  Kylem. `TargetSpec.count` already models N≥2 for destroy/exile/damage; the
  pump family is still N=1-only.
- **Mass damage with a compound selector** — "each creature **and each
  planeswalker**", Invasion of Karsus. The selector damage handler takes one
  selector, not a union.
- **X-scaled token creation** — "create X 2/2 … tokens", Invasion of New
  Phyrexia. `COUNT_X` exists as a fragment; the create-token handler doesn't
  use it.
- **The bespoke tail, one card each** — hand-authoring territory rather than
  parser work: stun counters (Kamigawa), "for as long as that card remains
  exiled, its owner may play it" (Gobakhan), "exile all cards from your hand,
  then draw that many" (Kaldheim), manifest (The Battle of Dragon Brothers),
  reflexive "when you do" triggers (New Capenna, Tarkir), fight-after-counter
  (Muraganda), "isn't exactly two colors" (Ravnica), power-X-or-less destroy
  (Lorwyn), "nonbattle permanent card" (Tolvada), scry-then-conditional-draw
  (Pyrulea), "sacrifices a creature or planeswalker of their choice" (Azgol),
  dig-until (Alara), a modal "choose one or both" ETB (Fiora), a phase
  trigger on "your combat step" (Occupation of Llanowar),
  search-for-a-typed-card-to-hand (Theros), look-at-top-N-reveal-one
  (Ixalan), and multi-clause mill/discard/draw (Amonkhet).

**What this sample shows.** One line of shared grammar —
`normalize._SELF_REFERENCE_RE` folding "this battle"/"this Siege" to `~` —
moved the pool 0 → 12, while the *card type* work itself moved it zero. The
gains that matter are almost always in shared grammar, and a fully
implemented mechanic is no guarantee its cards parse.

## Worked example: dungeon rooms (RULE 309)

Same lesson from the other direction: the RULE 309 dungeon engine and all
four room graphs (`game/dungeons.py`) were fully built while sitting at
21/30 modeled rooms — nothing dungeon-specific was missing, only ordinary
effect-body grammar (`room_effect_specs` runs the exact same
`segmenter.parse_effect_body` a card's own text does). PAR-13 (2026-08-04)
closed 8 of the 9 gaps: a P/T-delta route for `grant_until` plus its
"can't attack/block until `<duration>`" sibling (Fungi Cavern/Twisted
Caverns — both also picked up real non-dungeon cards via two new `_GROUP`
phrasings); a mandatory compound discard-then-triple-sacrifice handler
(Oubliette); a legendary named token (Cradle of the Death God — the first
`Card.is_legendary` a synthesized token ever carried); `ImpulsiveDrawEffect`'s
first oracle-text route, previously hand-authored-only (Runestone Caverns);
a new `DrawRevealCastOneFreeEffect` + a `"cast_free"` `choose_objects`
action, the first hand-zone pick that chooser ever offered (Mad Wizard's
Lair); and a new mass-interactive primitive, `RulesEngine.
request_each_player_pay_or` (RULE 101.4 APNAP, chained off the existing
single-player `request_pay_cost_then`) for "each player loses N life
unless they `<pay cost>`." (Veils of Fear/Sandfall Cell — the latter also
needed a new compound `ActivationCost.sacrifice` value,
`creature_artifact_or_land`, since the plain single-word sacrifice grammar
can't express an OR of three types).

**Throne of the Dead Three** ("Reveal the top ten cards of your library.
Put a creature card from among them onto the battlefield with three +1/+1
counters on it. It gains hexproof until your next turn. Then shuffle.")
is the one room left unmodeled — a genuine "reveal top N, choose one
matching a filter, place it with counters, shuffle the rest back" shape,
confirmed to have zero non-dungeon cache siblings (unlike every other gap
above, so there's no shared-grammar win waiting behind it). Left as an
honest residual rather than forced, the same call this document already
makes for the battle pool's own bespoke-tail cards.
