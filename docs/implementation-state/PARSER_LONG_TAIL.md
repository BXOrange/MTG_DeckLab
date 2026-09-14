# Oracle parser: the long tail — strategy & worked examples

The **examples** document of the three-way split (see
[BACKLOG.md](BACKLOG.md) for open tickets, `Done_*.md` for worklogs). Nothing
here is a ticket to close; it is the standing method for the indefinite part
of parser coverage, plus enumerated samples that calibrate how that tail
actually behaves.

Tracked in the backlog as a single standing entry, `PAR-12`.

**What does not belong here.** This file used to carry a per-`PARSER_VERSION`
changelog — ~1,500 lines of "v*N* shipped *X*, +*M* cards". That is a worklog,
and it lived here in duplicate: of the 426 distinct code identifiers it named,
399 were already documented in `Done_Backend.md`, usually in more depth and
filed under the subsystem the primitive belongs to. It was removed on
2026-09-09; **git history has it** if you need a specific version's wording.
The rules that replace it:

- **What shipped, and why it was built that way** → `Done_Backend.md`, under
  the subsystem heading for the primitive (extend the existing entry, don't
  append a new one).
- **What is still open** → `BACKLOG.md` if it is schedulable, or the
  *Known-open clusters* section below if it is long-tail residue.
- **Method, recurring lessons, worked samples** → here.

## Where coverage stands

**44.0% covered — 15,323 / 34,811 — as of 2026-09-14, PARSER_VERSION 379.**
Commander-legal slice (the one the product actually plays): **46.2% —
14,709 / 31,830** (measure with `--commander-legal-only`).

Measure with `scripts/coverage_report.py` (ledger-backed via
`services/coverage_db.py`), against the full ~35k-card Oracle universe;
add `--commander-legal-only` for the Commander slice, which records its own
`<v>-commander` snapshot row. `scripts/commander_tail_report.py` (read-only)
then segments the still-UNMODELED Commander-legal cards by *cause* — wrapper
re-measure (A), recurring template → `PAR-*` (B), set-specific → `PAR-*` (C),
missing engine primitive → `MEC-*` (D), bespoke hand-authoring tail →
PAR-12 (E).

"Covered" = parser-`MODELED` **or** hand-`AUTHORED`. Re-run the report rather
than trusting a figure quoted here, in `CLAUDE.md`, or in the Engine-Status
tab; after any change here, sync all three.

Goal is literal 100% of the Commander-legal slice (minus the RULE 123 sticker
non-goal); expect bucket E to stay several thousand one-card entries after
every generalisable cluster is closed.

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
  | Frodo, Sauron's Bane (the same DFC's back face) | — | Tales of Middle-earth (one card) | **Done** (2026-08-05) — hand-authored in `ability_catalogue.py`, no new engine primitive after all: a two-step RULE 613.6 standing conditional static driven by a plain custom counter, `ActivationCost.activation_condition` settable straight off a hand-authored `cost` dict, and a new `ConditionalEffect.ring_tempted_at_most` + `grant_triggered_ability`'s own `grant_effects` honouring a per-entry `condition` for the "…otherwise…" branch — see `Done_Backend.md`'s "Frodo, Sauron's Bane" entry |
  | Choose a Background | 702.124 | Commander Legends: Battle for Baldur's Gate | **Done** (2026-08-05) — bare FLAG keyword, inert in-game like Partner; the deckbuilding pairing check itself is [BACKLOG.md](BACKLOG.md)'s DB-3, still open |
  | Magecraft | ability word | Strixhaven | **Done** — `segmenter._MAGECRAFT_RE` |
  | Amass / Mutate / Monstrosity / Adapt / Goad / Bargain / Fading / Soulbond | 701.x / 702.x | War of the Spark / Ikoria / Theros / various | **Done** — see `Done_Backend.md`'s cEDH-cube batch |
  | Day/Night (werewolf transform) | 702.28 (2011+ template) | Innistrad: Midnight Hunt/Crimson Vow | **Done** — the *legacy* pre-2021 template is the one accepted non-goal above |
  | Specialize | digital/Alchemy (no paper CR) | Alchemy Horizons: Baldur's Gate | **Partially done** (2026-09-03, MEC-48) — `catalogue/keywords.py` recognizes a bare "Specialize {cost}" line; `effect_binder._specialize_activated_ability` binds it to a real sorcery-speed "{cost}, Discard a card" activated ability whose body is `SpecializeEffect` (a persistent `GameObject.is_specialized` designation + `EventType.SPECIALIZED` — **no** characteristic swap; the five per-colour specialized faces aren't in this repo's Scryfall seed, documented simplification); `segmenter._TRIGGER_VERBS` gains "specializes" → `SPECIALIZED`. +6 bare-cost cards (Gale/Jaheira/Rasaad/Vhal/Viconia/Wilson) + several specialized faces whose "when ~ specializes, `<modeled effect>`" body now parses. **Still open:** the "Specialize {cost}. `<rider>`" cards (cost-reduction / "activate only if" / alternate-zone riders) are held UNMODELED by `_SPECIALIZE_WITH_RIDER_RE` — each rider is its own small activated-ability-modifier follow-up (~5 cards: Imoen/Karlach/Shadowheart/Lukamina/…). |
  | Starting intensity | Duskmourn's Room-adjacent template | Duskmourn: House of Horror | **Not done** (checked 2026-08-05) — 0 cards SOLO-blocked on the phrase alone (always paired with another unclaimed clause); needs its co-blocker identified before estimating real scope |
  | Learn (Lessons) | 701.50 | Dominaria / Strixhaven | **Partially done** (checked 2026-08-05) — bare "Learn." is a 7-card SOLO cluster; the Lesson-sideboard-zone infrastructure itself (RULE 701.50a "look at your sideboard") isn't built, so a full deck with real Lessons stays out of scope regardless |
  | Investigate | 701.19a | Shadows over Innistrad (**reused across many later sets** — belongs on the *basic* track, listed here only as the worked example that motivated this split) | **Done** (2026-08-05) — a `create_token` alias onto the already-shipped Clue token, 87+ cards in one row; this is the case study for "keyword action, but basic not set-specific" — check *reuse breadth* before filing something here |
  | Station | 702.184a / 721 | Edge of Eternities | **Done** (2026-08-27) — a third "striated text box" grammar alongside Leveler/Class (`catalogue/station.py`), the reminder-line activated ability bound structurally off Scryfall's own `keywords: ["Station"]` entry (`effect_binder._station_activated_ability`); see `Done_Backend.md`'s Station entry |
  | Horsemanship | 702.31 | Portal (Portal-only, no reprints since) | **Not done** (checked 2026-08-27, RULE 702 keyword audit) — bare keyword, `combat.can_block` never checks it; lowest priority of this whole table, essentially a dead card pool |
  | Banding | 702.22 | Alpha/old-border era | **Not done** (checked 2026-08-27) — bare keyword, 0 `game/` hits; nostalgia-only, no modern reprints |
  | For Mirrodin! | 702.90-adjacent | New Phyrexia | **Recognition fixed** (PARSER_VERSION 101, PAR-28) — the trailing-`!` keyword line is now claimed (`_KEYWORD_TOKEN_RE`); no engine behaviour (Living Weapon-style germ token) yet |
  | Max Speed / Start Your Engines! | RULE 702.178 / 702.179 | Aetherdrift | **Done** (PARSER_VERSION 101, PAR-28) — full Speed subsystem: `Player.speed`, the Start-Your-Engines! SBA, the RULE 702.179d life-loss inherent trigger, `your_speed_is_max` static gate. See `Done_Backend.md`'s "Keyword — [ability] families" entry |
  | Job Select / Tiered / Increment / Paradigm / Teamwork / Sneak | various | Final Fantasy | **Not done** (checked 2026-08-27) — recognized-but-inert; Sneak's name also collides with an unrelated hand-authored effect, worth disambiguating before building. (**Power-up** was in this row — now **done**, PAR-28) |
  | Space Sculptor | — | Warhammer 40,000 (Commander) | **Not done** (checked 2026-08-27) |
  | Living Metal / More Than Meets the Eye | — | Transformers (Commander) | **Not done** (checked 2026-08-27) |
  | Web-slinging | — | Spider-Man | **Not done** (checked 2026-08-27) |
  | Firebending / Mobilize | 702.189 / 702.181 | Avatar: The Last Airbender / Tarkir: Dragonstorm | **Recognition done, behaviour not** (PARSER_VERSION 100, PAR-27) — "Firebending X, where X is …" / "Mobilize X, where X is …" no longer drops the card to `UNMODELED` for a formatting reason (the keyword line is claimed, inert — same as a plain "Firebending 2"); the variable-N token/damage behaviour is still unbuilt |
  | Infinity | — | (product TBD at audit time) | **Not done** (checked 2026-08-27) — 0-2 cache hits |
  | Warp | 702.185-adjacent | Bloomburrow | **Not done** (checked 2026-08-27) — distinct from the unrelated "Warp" collision noted for the Final Fantasy row above; verify regex scoping before building either |
  | Exhaust, Solved, Boast, Forecast | RULE 702.177 / 702.169 / 702.142 / 702.57 | Edge of Eternities / Murders at Karlov Manor / Kaldheim / Dissension | **Done** (PARSER_VERSION 101, PAR-28) — the whole "Keyword — `<ability>`" label family bound with its real restriction (Exhaust/Power-up once-per-game, Boast attacked-this-turn + once-per-turn, Forecast from-hand + upkeep-only, Solved's Case solve state machine). Per-card oracle coverage of individual Cases is still long-tail (an unbuilt "N …this turn" solve-condition tracker, or an effect-body gap in a `Solved —` clause) — the *mechanism* is done, same standing as the battle pool. See `Done_Backend.md`'s "Keyword — [ability] families" entry |
  | Mayhem, Decayed | various | Duskmourn: House of Horror | **Not done** (checked 2026-08-27) — Decayed also has real combat-restriction implications (can't block, 2 damage then sacrifice), not just a cost/cast wrapper |
  | Double team (+ Conjure / Draft from a spellbook / Boon / perpetual) | — (Alchemy digital keyword, no CR RULE 702 number) | Alchemy Horizons: Baldur's Gate / Dominaria | **Not done** — noted by PAR-27's keyword audit (2026-08-28): "Double team" is absent from `catalogue/keywords.py`'s CR-scoped `_TABLE`, so "Flying, double team" / "Menace, double team" lines fail `is_keyword_line`. ~18 cache cards, all also-blocked on other unmodelled Alchemy mechanics (Conjure/Draft/Boon/perpetual). Recommend deciding the whole Alchemy keyword family as one unit (likely a non-goal like Vanguard — Alchemy cards aren't paper-Commander-legal, so they're outside the `--commander-legal-only` coverage scope anyway) rather than adding "double team" piecemeal |

  The rows above come from a 2026-08-27 systematic audit of all 195
  registered `parser/oracle/catalogue/keywords.py` entries against real
  `game/` consumers (not just cache LIKE-counts) — see `BACKLOG.md`'s
  `PAR-22` through `PAR-26` for the audit's full findings, including the
  **evergreen** gaps it found alongside these set-specific ones (Prowess,
  Affinity, Delve, Shroud, and a dozen others — those belong on the
  *basic* track, not this table, since they recur every set rather than
  being confined to one product). Several of the rows above are still first-pass
  cache-count estimates (0-2 hits at audit time, not yet `parser_probe.py
  blocked`-verified per this section's own rule) — verify before sizing a
  build, don't just copy the status.

  Doctor's companion / Time travel (Doctor Who), Augment (Aether Revolt),
  ki counters (Kamigawa block), and whatever Lorwyn Eclipsed/New
  Capenna/further Bloomburrow-block sets turn out to print as their own
  signature mechanic are all **known-unverified** — real cards may be
  blocked on some of these phrases (see `rank`'s live output), but nobody
  has yet confirmed scope/primitive-existence for them the way the rows
  above were. Don't copy a status onto this list without running the
  check yourself.

## Known-open clusters

Long-tail residue that no open ticket names — salvaged when the per-version
changelog was removed, because most of it had been filed under `PAR-30`,
`PAR-60`, `MEC-77` and the Clash/Airbend bullets, **all since closed**. None of
it is schedulable as written; it is sizing material for the next pass, in the
same spirit as the worked examples below.

**Verified against the v298 ledger on 2026-09-09** — every row below is a card
that is `unmodeled` *today*, and the blocker quoted is its **actual** remaining
unclaimed clause, not the description its original batch wrote. That check
mattered: of the 61 cards the changelog listed as open, **25 were already
`MODELED`** and eight whole clusters had closed underneath their own notes —
the threaten/gain-control family (Broadcast Takeover, Call for Aid, Furnace
Reins, Loki's Scepter, Flayer of Loyalties, Goatnap, Awaken the Sleeper), the
O-Ring two-sentence templating (Oblivion Ring itself, Crack in Time, Driftgloom
Coyote, Food Coma, Brutal Cathar), dynamic Incubate (Excise the Imperfect,
Sunfall), colour-filtered targeting (Combust, Snow Hound, Tidebinder Mage,
Offspring's Revenge), `normalize`'s legendary short names (Kaalia of the Vast,
Owlbear Cub, The Vast Scrier), "tapped and attacking" (Winota, Kari Zev),
majority/permanent vote ballots (Council Guardian, Council's Judgment), and the
RULE 508.1g attack-tax opt-out (built in v288). Two more entries named a
blocker that had been fixed while the card stayed unmodeled on something
unrelated. **Re-run this check before sizing anything below** — that is this
document's own standing rule, and it has now caught itself.

| Cluster | Still open | Cards |
| --- | --- | --- |
| Becomes-target self-sacrifice | "sacrifice it **unless you discard a land card**"; the quoted-ability grant forms (`… has "when ~ becomes the target of a spell or ability, …"`) | Cursed Monstrosity · Crystalline Nautilus, Dismiss into Dream, Boneshard Slasher, Makeshift Mannequin |
| Quoted-ability grant until EOT | the compound "gets +2/+0 **and** gains '…'" wrapper | Demonic Gifts |
| Return-to-battlefield destination | "return it to the battlefield **face down**", and its flipped/transformed siblings | Ashcloud Phoenix, Homura Human Ascendant, Loyal Cathar |
| Mass graveyard return, riders | riders on the returned cards (an extra counter, "each of them is a 1/1 Spirit"); "…that weren't put there this way" | Pyrrhic Revival · Storm of Souls · Bringer of the Last Gift |
| Distribute counters + tail | "distribute N +1/+1 counters among 1, 2, or 3 target creatures, **then** …" and the post-distribute "each of those creatures" tail | Biogenic Upgrade, Court of Garenbrig |
| Counter doubling, union target | "double the number of **each kind of** counter on target **artifact, creature, or land**" | Vorel of the Hull Clade |
| Land destruction, search tails | the "…each player searches…" / "…that land's controller searches…" follow-up after the destroy | Field of Ruin, Demolition Field, Magmatic Hellkite |
| Loses-all-abilities + base P/T | "loses all abilities and becomes a `<colour>` `<type>` with base power and toughness N/N"; the front-loaded "until end of turn, … has base P/T … and gains `<kw>`" form | Turn to Frog, Snakeform, Ovinize · Creeperhulk |
| Cost reduction gated on the target | "this spell costs {N} less to cast **if it targets** a creature (card) with mana value N or less / with a +1/+1 counter on it" | No One Left Behind, Revoke Demise, Titanic Brawl |
| Un-limited batch-death triggers | "whenever **1 or more** other creatures [you control] die, …" with no "only once each turn" limiter to collapse the per-object firing into the right net | Great Fierce Bee, Vengeful Townsfolk |
| Halved, rounded X | "you gain **half X** life and draw **half X** cards. round down each time" | Hydroid Krasis |
| "destroy ~ unless you pay" follow-up | "**if ~ is destroyed this way**, …" | Cosmic Horror |
| Random modal + emblem body | "choose 1 **at random** —", plus an emblem whose own body is unclaimed; "you may planeswalk" (only the bare "planeswalk" fullmatch exists) | Seek Bolas's Counsel · Start the TARDIS |
| Threaten after-tail | "…**create a Blood token**" after the gain-control / untap / haste sequence | Bloody Betrayal |
| Saddle referent | "whenever ~ attacks **while saddled**, choose a nonlegendary creature that saddled it this turn" | Calamity, Galloping Inferno |
| Compound attack-trigger conditions | "whenever ~ attacks, **if** a nonland permanent left the battlefield this turn **or** a spell was warped this turn, …" | Alpharael, Stonechosen |
| Misc singletons | "another target creature" (the `other_creature` kind is not engine-wired); "**if it was a Gideon planeswalker**" conditional tail | Arwen, Mortal Queen · Gideon's Defeat |

## Lessons that keep recurring

Each was paid for once; re-reading them is cheaper than re-learning them.

- **"Still open" notes written inside a shipped batch's narrative go stale
  silently, and nothing points at them once the batch's ticket closes.** The
  removed per-version changelog ended most entries with a residue list ("still
  open in this cluster: …"). Those lists were the only record that those gaps
  existed — but they were filed *under the version that closed something else*,
  so when `PAR-30`, `PAR-60` and `MEC-77` closed, the residue kept no home and
  nobody re-checked it. Auditing the 61 cards named that way on 2026-09-09
  found **25 already `MODELED`**, eight clusters wholly closed, and two entries
  whose named blocker had been fixed while the card stayed unmodeled on
  something unrelated. This is `CLAUDE.md`'s no-half-implementations rule seen
  from a third angle: not a deferred item rolling over, but a *recorded gap
  losing its owner*. Residue belongs in a place someone re-reads (`BACKLOG.md`,
  or this file's *Known-open clusters*), never as a trailing sentence on a
  worklog entry.

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
- **Scryfall's own `keywords` array is noisy — cross-reference before
  treating a raw string as a real keyword.** It mixes RULE 702 keyword
  *abilities* (what `catalogue/keywords.py` tracks), RULE 701 keyword
  *actions* (Mill/Scry/Investigate — a structurally different mechanism,
  ordinary verbs handled by `handlers.py`), created-token type names
  (Treasure/Food), and — the majority by distinct-string-count — one-off
  card-specific *flavor* ability names Scryfall's own keyword-extraction
  heuristic mistakes for a reusable keyword whenever a card prints the
  "Name — effect" ability-word template with a novel name ("10,000
  Needles", Jumbo Cactuar). A diff of "every distinct raw `keywords`
  string not in our registry" (2026-08-28) found 689 distinct strings —
  almost none of them a real registry gap; see `normalize.
  _strip_unregistered_keyword_labels` (PARSER_VERSION 99) for the fix this
  specific noise pattern led to.
- **At scale, "verify before sizing" can invalidate an entire `rank`
  top-N in one pass, not just one entry.** 2026-08-28 (was ticket PAR-20,
  now closed): six of the highest-count templates in a fresh cache-wide
  `rank` (40-240 raw hits each — "choose N —", "you get an emblem with
  `<name>`", "costs `<cost>` more … for each target beyond the first", the
  O-Ring "exile … until ~ leaves", "enchanted creature has `<name>`", the
  2011+ werewolf transform condition) were checked with `parser_probe.py
  blocked`, and *all six* turned out to already be fully claimed by
  existing grammar — every card's real blocker was a distinct, unrelated,
  one-off co-resident clause (`blocked`'s "what else blocks those cards"
  residue came back essentially all count-1). This isn't a one-off miss;
  it's a sign the basic-mechanics (cache-wide) track's easy big wins are
  genuinely thinning out at the current coverage level (~35.5%), not just
  a bad `rank` run. The one discrete win squeezed from that residue
  afterward — RULE 604.3's "power and toughness are each equal to the
  number of `<X>`" CDA-P/T handler (PARSER_VERSION 105, +20 cards) — was
  the exception that proves it: a genuinely unrecognized shape, but a
  narrow whitelisted one, not a big generic family. When this happens,
  don't keep re-running `rank` hoping for a better top-N — switch to the
  deck-first track instead (a real saved deck's cards are far more likely
  to share an actual unfixed pattern than the whole-cache aggregate is at
  this point).
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
