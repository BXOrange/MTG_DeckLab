# Backlog — open work, as tickets

**The single list of open work, backend and frontend.** Replaces the former
per-half `ToDo_Backend.md` / `ToDo_Frontend.md`, which no longer exist.

Three kinds of document, kept strictly apart — put a new line in the right
one:

| Kind | Lives in | Rule |
| --- | --- | --- |
| **Open points** | this file | Only open scope. No history. |
| **Worklogs** | [Done_Backend.md](Done_Backend.md), [Done_Frontend.md](Done_Frontend.md) | Append-only. What shipped and *why it was built that way*. |
| **Examples** | [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) | Calibration samples + strategy for the indefinite parser tail. |

**Closing a ticket = deleting it from this file** and appending its narrative
to the matching `Done_*.md` section. Never leave a `[x]`, a "shipped" note,
or a "moved to Done" pointer here — this file is read in full, often, so
anything finished that stays costs every future read. If only part of a
ticket is done, keep only the part that isn't.

Ticket ids are stable; reuse a retired id only for the same subject.
Plan-level sequencing lives in
[10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).

**Parked tickets and permanent non-goals live in [DEFERRED.md](DEFERRED.md)**,
not here — low-priority / large-and-unscheduled work, plus the "never to be
built" guardrails (Stickers, Attractions, Vanguard avatars). Keeping them out
of this file is deliberate: `BACKLOG.md` is read in full often, so it holds
only work that's actually up for scheduling. Promote a parked ticket by moving
its block back into the matching section here.

| Prefix | Category |
| --- | --- |
| `ENG` | Game engine — turn/stack/priority loop, layers, targeting, combat plumbing |
| `PAR` | Parser — oracle-text → `AbilitySpec` recognition (`parser/oracle/`) |
| `MEC` | Game mechanics — a named MTG mechanic with no engine primitive yet |
| `PLR` | Player management — seats, multiplayer, bots, accounts, sessions |
| `VIS` | Visuals — frontend UI/UX |
| `DB` | Database — card cache, saved decks, persistence, data freshness |
| `ANA` | Deck analysis — UC2 (LLM + presentation) |

---

## ENG — Game engine

> Scope and rationale for ENG-37 live in
> [14_PARSER_GRAMMAR_DESIGN.md](../concepts/14_PARSER_GRAMMAR_DESIGN.md);
> the evidence is
> [13_ORACLE_PARSER_GRAMMAR_REVIEW.md](../concepts/13_ORACLE_PARSER_GRAMMAR_REVIEW.md).
> Order is a dependency chain, not a preference.
>
> **ENG-34 is closed** (`game/isa.py`, `scripts/isa_report.py`,
> `tests/test_isa_inventory.py`, `tests/test_target_frames.py`). The two
> below read their backlogs off it rather than re-deriving them:
> `isa.fusions_retired_by(<op>)` is ENG-37's fusion backlog split by
> operator — a first-pass count that ENG-37 found over-states (see its
> ticket).
> Its cheap-exit checkpoint **passed** — all 50 top corpus operations
> resolve to one framed instruction — so the design stands rather than being
> dropped.
>
> **ENG-36 is closed** (`game/effect_conditions.py`, the widened
> `game/static_conditions.py`, `tests/test_effect_conditions.py`).
> `ConditionalEffect._condition_holds` went 554 → 16 lines and the parser's
> fifteen condition peelers became one rule. Two corrections to this
> ticket's own text, for whoever reads it in the history: the cascade was
> **15** hand-written blocks, not 26 (26 counted distinct *outcomes*), and
> `created_object` was deliberately not added as a referent — nothing
> produces or needs one, and the subject axis is a dict row away whenever
> something does.
>
> **ENG-35 is closed** (`game/continuations.py`,
> `RulesEngine.open_choice`/`resolve_choice`, `tests/test_continuations.py`).
> `RulesEngine` went 254 → **162** public methods and the dispatcher 367 →
> 23 lines. ENG-37's blocker is gone: `GameState.deferred_effects` now
> carries a `DEFERRED_ITERATION` frame (`RulesEngine.defer_iteration`), so a
> loop body can suspend mid-iteration and resume at the next item.

- **ENG-37 · Retiring the fused effect types (`14_` S3, continued).** The
  **composition nodes are built and shipped** — `game/effects/composition.py`
  registers `seq`/`if_else`/`optional`/`for_each`/`bind`, `game/effect_
  amounts.py` is `bind`'s measured-quantity vocabulary, and
  `isa.Classification.COMPOSITION` records axis 3 as existing. Frodo, Sauron's
  Bane is the first card on it (its complementary-conditional pair is now one
  `if_else`). **Fusion count: 62** (down from the first-pass 84; migrations to
  the operand/`bind`/`seq` axes and misclassification fixes are catalogued in
  `Done_Backend.md`'s "Fusion retirement" section). What remains is retiring
  the rest, and the reason that is a separate piece of work is measured
  rather than assumed:

  - **Only 9 of the fusions are emitted by `parser/oracle/` at all** — the
    rest are hand-authored `ability_catalogue` entries. And "parser side
    exists" is not "cleanly retirable": `impulsive_draw` (~11 catalogue call
    sites, card-specific params) and `blink` (a reusable primitive) are
    entangled across producers; `return_from_graveyard_transformed` /
    `reveal_top_conditional_to_hand` / `draw_reveal_cast_one_free` are genuine
    axis-4 linkage needing referent/continuation wiring inside the node. See
    `Done_Backend.md`'s parser-side scan.
  - **Most fusions have every part already registered as a standalone
    instruction** (`pay_cost` ×3 and `investigate` ×1 are the only missing
    operations), so the blocker is not a missing operation and not the
    composition axis either.
  - **The blocker is axis 4 — linkage.** A fusion exists because its second
    part must name what the first part *produced*, and an effect's **operands**
    have no general way to name a referent. `exile_gain_life_equal_power` says
    so in its own docstring: "composing two effects here couldn't pass the
    power along". Same for `destroy_gain_life_to_controller` ("its controller"),
    `reveal_top_conditional_to_hand` ("if it's a land"),
    `create_token_may_attach_equipment` ("attach to the token you just made"),
    `each_player_exile_from_graveyard_then_counters` ("that many").
  - **The operand axis is now built** (`game/effect_operands.py`): an
    operand may name a referent, e.g. `gain_life` with
    `player={"of": "previous_target", "as": "controller"}`. Three fusions
    retired onto it as proof of the pattern (**84 → 81**) — Swords to
    Plowshares, Nature's Claim, Feed the Swarm. Only `gain_life`/`lose_life`
    are wired so far (`GameEffect._operand_player`, one intercept per fallback
    chain).

  - **Batch plan — cluster by mechanism, not by operator.** The remaining 76
    are ~7 shared mechanisms, not 76 problems (the `*_create_token` classes
    say so themselves: *"the same 'read something off the target, then act'
    shape"*). Each batch **builds one mechanism and sweeps every `_FUSION_
    TYPES` row it clears in the same pass** — grep the table before starting
    and again when the primitive lands (CLAUDE.md "No half-implementations").
    The rows are a menu, not a strict order. **B4 and B8 are fully retired**;
    so are the `*_create_token` and Crypt Incursion parts of B3. What is left
    needs genuine new vocabulary: the remaining B3 rows a sum-over-a-list
    amount kind + a previous-moved-object referent; B5 the revealed-card
    referent; B6 depends on B3+B4; B9 needs ENG-35 coordination.

    | # | Mechanism to build | Clears (approx) | Notes |
    | --- | --- | --- | --- |
    | **B3** | recipient/amount referent operands. The `*_create_token` slice and Crypt Incursion (`exile_graveyard_creatures_gain_life`) are retired (needed ~no engine code — see `Done_Backend.md`). **Remaining:** a **sum-over-a-list** `effect_amounts` kind (`exile_top_then_damage_by_mv`/`mill_..._by_mv` deal *summed* MV of N moved cards) and a **"the object(s) the previous instruction moved"** referent, plus `copy_object`/`attach` operand wiring. | `create_attached_aura_token`, `create_token_copy_of_linked_exile`, `copy_self_controlled_by_previous_target`, `copy_attachments_onto_last_created`, `exile_top_then_damage_by_mv`, `mill_then_damage_each_opponent_by_mv` (~6) | genuine new vocabulary |
    | **B5** | **foundation shipped** (batch 9): `GameContext.revealed_card` + `reveal_top`/`put_revealed_card` effects + the `of: "revealed"` referent. `reveal_top_then_take_and_lose_life` (Dark Confidant) and `reveal_top_then_land_battlefield_or_draw` (Thrasios) retired onto it. **Remaining rows each need more:** `reveal_top_conditional_to_hand` (Goblin Guide — parser-emitted, so re-emit `_reveal_top_conditional` as the `seq` form + `PARSER_VERSION` bump); `reveal_top_then_free_cast_if_mv_match` / `reveal_top_then_counter_if_mv_match` (cast-from-library / a counter tied to the reveal); `reveal_top_then_maybe_battlefield_if_land_or_cheap_creature` (a "you may" + a dynamic MV-vs-loyalty predicate); `reveal_top_then_creature_and_or_land_battlefield` (reveal N, interactive pick of a creature and/or a land); `exile_then_reveal_greater_mana_value` | `reveal_top_conditional_to_hand`, `reveal_top_then_counter_if_mv_match`, `reveal_top_then_free_cast_if_mv_match`, `reveal_top_then_maybe_battlefield_if_land_or_cheap_creature`, `reveal_top_then_creature_and_or_land_battlefield`, `exile_then_reveal_greater_mana_value` (~6) | `reveal_top_then_transform` folds in (acts on self) |
    | **B6** | depends on B3: `optional`/`seq` body of `[<verb>, grant_keyword/grant_until on previous_target|source]` — the "if you do, it gains …" shape | `return_creature_grant_indestructible`, `unattach_tap_indestructible`, `return_top_graveyard_creature_with_haste`, `exile_discount_cost`, `exile_top_then_grant_conditional_cast`, `exile_triggering_discard_may_play_this_turn`, `impulsive_draw` (~7) | `impulsive_draw`'s ~11 call sites + `count_if_additional_cost_paid` param are the real cost here |
    | **B7** | `bind` over `hand_size` / a new `cards_discarded_this_way` `THIS_WAY_TALLIES` entry; `wheel`/`windfall` are `for_each`-over-players wrapping that `bind` | `exile_hand_then_draw_that_many`, `discard_up_to_then_draw_that_many`, `windfall`, `wheel`, `wheel_of_fortune` (~5) | `DiscardCardsDiscardedDeltaDrawEffect` already reads the delta — half-built |
    | **B9** | coordinate with **ENG-35** + bump `test_isa_inventory`'s `CONTINUATION ≤ 59` / `SPECIAL ≤ 42` pins in the same commit | `taxed_draw`, `exchange_control_then_energy_sacrifice`, `pay_life_equal_to_opponents_combat_damaged_draw_that_many`, `destroy_controller_may_search_basic_land`, `exile_controller_searches_basic_land`, `shuffle_target_graveyard_cards_into_library`, `draw_reveal_cast_one_free`, `remove_counters_from_among_then_draw_lose_life` (~8); plus `haunt` → INSTRUCTION, and the bespoke one-card residue → SPECIAL | these open a `pending_choice`, so they are ENG-35-shaped, not axis-3; the two pins being *exact* is the coordination point |

    Internal plumbing (`draw_mill_if_discarded`, `draw_lose_life_counter_
    removed_delta`, `sacrifice_count_draw_lose`) retires **with its parent
    CONTINUATION effect** in B9, never on its own.

    The table names the mechanism clusters (~55 rows); the ~20 not listed
    (the `for_each` family — `each_player_counter_then_protection`,
    `each_player_exile_from_graveyard_then_counters`,
    `owner_draw_others_lose_per_dying_counter`,
    `exile_top_from_each_player_cast_free`,
    `create_tokens_per_counter_among_target_player_creatures` — plus
    `<verb>+create_token`/`<verb>+reveal`/`copy`-variant `seq`/`if_else` rows)
    fold into whichever batch's pre-start grep claims them: the `for_each`
    ones are B7 bodies (or a retired-B4 pronoun body) wrapped in the existing
    `for_each` node, the rest are B3 (referent) or B5 (revealed-card) once
    those mechanisms exist. Any
    row still standing after B3→B9 is a genuine one-card SPECIAL — hand-author
    and bump the `≤42` pin.

  - **Re-derive before using the count as a target.** Inspection keeps finding
    the classification over-states: `wheel`/`wheel_of_fortune` are `for_each`
    with a fixed draw, not `bind` (nothing is measured); several `seq` rows
    (`haunt`, `taxed_draw`, `blink`) are single rules concepts rather than
    welded pairs; `dies_grants_rad_counters_equal_power` was tagged
    `create_delayed_trigger`+`put_counter` but has no delayed trigger at all
    (retired as a plain `bind` over `put_counter`, `Done_Backend.md`);
    `create_token_copy_of_named` / `shuffle_self_into_library` /
    `shuffle_graveyard_into_library` / `exile_return_transformed` /
    `return_from_graveyard_transformed` were welds only on paper — one atomic
    engine call each (now `ALIAS`); `draw_if_trigger_object_greatest_power`
    (→ `draw`) and `reveal_top_then_transform` (→ `transform`) were one-"part"
    gated effects, not welds (now `ALIAS`).
  - **Exit:** the batch plan above worked through B3→B7 + B9 (B8 done),
    `_FUSION_TYPES` empty, `isa.Classification.FUSION` retired. Track progress
    with `scripts/isa_report.py --registry` (fusion count) and
    `isa.fusions_retired_by(<op>)`.

## PAR — Parser

- **PAR-61 · Parser grammar/IR restructure: umbrella and order.** Evidence:
  [13_ORACLE_PARSER_GRAMMAR_REVIEW.md](../concepts/13_ORACLE_PARSER_GRAMMAR_REVIEW.md).
  Design:
  [14_PARSER_GRAMMAR_DESIGN.md](../concepts/14_PARSER_GRAMMAR_DESIGN.md).
  The parser is a whole-clause lookup table (`EffectHandler` uses
  `regex.fullmatch`) over an IR with no sequencing/branching/binding node, so a
  *combination* of two known effects must be memorized rather than derived -
  **22,753 distinct unclaimed templates for 20,328 blocked cards**, 80.0% of
  them failing on exactly one clause. The operation vocabulary underneath is
  closed: **130 operations, top 50 covering 94.9%**. The explosion is
  combinatorial, not lexical.

  Execution order (dependency chain): ~~ENG-34~~ (atom inventory, **closed**)
  → ~~ENG-35~~ (continuations, **closed**) → ~~ENG-36~~ (structured
  conditions, **closed**) → **ENG-37** (composition axis **shipped**; fusion
  retirement remains). The grammar and slot-grammar stages that followed are
  complete; this umbrella now waits only on fusion retirement.

  This ticket now holds only its two standing guardrails, live until ENG-37
  closes:

  - **Do not displace the per-template track.** `PAR-12` / `PAR-31…PAR-53`
    remain where the near-term coverage is; `13_` section 5.6 confirms it. Note
    in particular the **1,279 clauses where the trigger body already parses and
    only the condition fails** — the cleanest isolated target in the remainder,
    needing none of this restructure.
  - **Read `13_` section 5.6(a) with care.** Holding the atom inventory fixed at
    what the handler table claims today, composition alone flips only 5.3% of
    blocked cards. That bounds *retrofitting* composition, not *atoms +
    composition* — the payoff is multiplicative. An earlier draft drew the wrong
    conclusion.

- **PAR-12 · The indefinite long tail (methodology pointer, not a closeable
  ticket).** Strategy, coverage, and worked examples live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Two tracks: **basic
  mechanics** (generic shapes, cache-wide yield) — easy big wins
  **exhausted** as of 2026-08-28 — and **set-specific mechanics**
  (a set/precon's signature keyword, worked deck-first against a saved
  deck), now the primary track: audit a real deck's card list, don't
  re-mine `rank`. Planechase/Archenemy plane/scheme card *bodies* fold in
  here too (triggers already recognized, ~13/309 bodies done) — not a
  separate ticket.

  > **Ticket-id note:** every number from `PAR-1` through `PAR-30` is
  > already a real, shipped, cross-referenced ticket elsewhere in this
  > codebase (grep before reusing one — `PAR-14`, for one, is RULE 603.2's
  > once-per-turn trigger limiter, `Done_Backend.md`, nothing to do with
  > keywords; `PAR-30` was `PAR-29`'s parser trail, closed PARSER_VERSION
  > 216 — all 24 RULE 701 keyword actions have recognition + an engine
  > primitive, and its last residue moved to `MEC-52`, closed). The first free
  > parser ticket id is **`PAR-65`** (checked 2026-09-10): `PAR-31…PAR-53` are
  > the Commander-legal tail clusters below, `PAR-54`/`PAR-55`/`PAR-57`/`PAR-60`
  > `PAR-56`/`PAR-58`/`PAR-59`/`PAR-64` are open below, and `PAR-61` is the
  > grammar-restructure umbrella above.

- **PAR-31…PAR-53 · Commander-legal tail — one PAR per recurring template
  cluster.** Seeded from `scripts/commander_tail_report.py` (read-only,
  segments every still-UNMODELED **Commander-legal** card by *cause* into
  buckets A–F; A = wrapper/segmenter re-measure, B = recurring template, C =
  set-specific mechanic, D = missing primitive → `MEC-*`, E = bespoke
  hand-authoring tail → PAR-12). The `#` below is the tool's
  Commander-legal SOLO upper bound at the run cited — **re-run the tool and
  `parser_probe.py blocked '<regex>'` before starting a batch**, the real
  SOLO count is always lower. Close each the normal way (delete the line,
  narrate in `Done_Backend.md`, bump `PARSER_VERSION`, sync the three
  coverage figures, sweep for siblings). Full method:
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Counts below are from a
  PARSER_VERSION 186 run (2026-09-01) and are stale; a fresh v298 segmentation
  is in
  [13_ORACLE_PARSER_GRAMMAR_REVIEW.md](../concepts/13_ORACLE_PARSER_GRAMMAR_REVIEW.md)
  §5.3. Every ticket shall be completed end to end without leaving residue
  before moving to the next ticket.

  Bucket B (recurring effect-body / static templates, `extend-parser` loop):

  - **PAR-33** — Aura/Equipment grants a *quoted* ability
    (`enchanted/equipped creature has "…"`, `… gets +N/+N and has "…"`,
    `enchanted land has "…"`) (~#21+9+9).
  - **PAR-34** — tribal / state lord. Left: `all slivers have "…"` (~#13 —
    a group-scoped **quoted-ability** grant, recursively parsed) and the
    Odyssey **Threshold** quoted-ability bodies (~#25 — the same
    quoted-ability-grant machinery, wrapped in the `active_if` gate).
  - **PAR-35** — casting-timing restriction (`cast this spell only during
    the declare attackers step and only if you've been attacked`,
    conditional flash `as though it had flash if you pay <cost> more`, the
    `… flash. if you cast it any time a sorcery couldn't …` templating)
    (~#14+9+9).
  - **PAR-36** — trigger-condition vocabulary. Left: `whenever you
    draw your second card each turn` (~#12), `…discards **that many** cards`
    reading the DAMAGE amount (Dreamstealer / Needle Specter — a
    `DiscardEffect.count_from_trigger_event`), `whenever you cast a spell
    that targets ~` (~#8).
  - **PAR-38** — residue only. The upkeep-damage **riders** — `~ deals <n>
    damage to you for each <X>` (Black Market Tycoon — needs a
    count-selector) and `~ deals <n> damage to you unless you pay <cost>`
    (Force of Nature / Minion of Tevesh Szat — a self-scoped `unless you
    pay` branch); plus `skip your draw step this turn` as a conditional "if
    you do" tail (Elfhame Sanctuary).
  - **PAR-39** — old two-sentence O-Ring templating (`when ~ leaves the
    battlefield, return the exiled card to the battlefield under its
    owner's control`) (#12) — **reuse the PAR-30 Threaten/O-Ring cluster**.
  - **PAR-41** — additional cost `{X}` / from graveyard. Left: `discard
    x cards` and `exile x [creature] cards from your graveyard` — both need
    an **X-scaled additional cost** (the `additional_cost` fields carry a
    fixed int / the `pay_life` `"x"` sentinel, no general X-scaled
    non-mana-cost path yet).
  - **PAR-42** — conditional / dynamic enters-tapped & entry counters.
    Left: `if it's neither day nor night, it becomes day as ~ enters` (#10).
  - **PAR-43** — self CDA / `for each` P/T. The `~ gets +N/+N for each <X>`
    standing self-anthem form has its general handler
    (`_SELF_ANTHEM_FOR_EACH_RE`) but only for the "for each <X>" quantities
    that already have a `continuous.count_selector`; the remaining tail
    (~120 SOLO, ~40 distinct selectors — "Equipment you control"
    board-wide, "oil counter on it", "aura attached to it", "experience
    counter you have", per-subtype "other <type> you control", …) is one
    new `count_selector` per phrase in `continuous.py`, plus the **Aura**
    form (`enchanted creature gets +N/+N for each <X>` — `affects=
    "attached_permanent"` instead of `"self"`).
  - **PAR-44** — static permission / prohibition. Left: `a deck can have any
    number of cards named ~` (#10) — a deckbuilding clause,
    claim-without-spec.
  - **PAR-45** — ETB compound utility. Left: `as ~ enters, choose an
    opponent` (#10).
  - **PAR-46** — cost reduction `for each creature card in your graveyard`
    (#9) and the Party count-selector (see PAR-50).
  - **PAR-47** — `<cost>,<cost>: put a charge counter on ~` + its
    remove-a-charge-counter spend clause (#14).
  - **PAR-49** — `<cost>: ~ becomes the creature type of your choice until
    end of turn` (#8).
  - **PAR-50** — combat-damage-assignment statics (`you may have ~ assign
    its combat damage as though it weren't blocked` #9, `each creature you
    control assigns combat damage equal to its toughness rather than its
    power` #6).
  - **PAR-51** — `start` (#12) and `storied` (#9) — parse traces first;
    `start` looks like a Jump-start/Aftermath split artefact, `storied`
    like a LOTR one-off. Investigate before sizing.

  Bucket C (set-specific mechanics, deck-first):

  - **PAR-52** — Ki counters / "Spirit or Arcane spell" cast trigger
    (Kamigawa) (#51).
  - **PAR-53** — Party (Zendikar Rising): `creatures in your party` /
    `full party` count-selector + its cost-reduction form (#39; shares the
    count-selector with PAR-46).
  - Doctor's companion (Doctor Who) (#28), Rebel/Mercenary recruiter
    tutor chains (Mercadian Masques) (#21), `enters prepared` (#23) —
    file from the next free id (see the ticket-id note above) when their
    batch comes up; not enumerated further here to keep the list to the
    first wave.
  - **Non-goal / lowest priority, no ticket:** Attractions (RULE 717,
    #19 — permanent non-goal), Conspiracy draft-matters (#13), Banding
    (#13), Horsemanship (#8) — dead pools / non-goals, documented, kept
    out of the denominator with the sticker cards.

  **Bucket A residue — modal *header* shapes** (bodies all claim; only the
  header/engine support is missing). What is left, ~26 Commander-legal cards
  in five shapes:

  - **PAR-56 · Teamwork modal and rider grammar (RULE 702.194).** Route
    `if this spell was cast using teamwork` modal overrides and ordinary
    conditional riders to a `teamwork_paid` condition. The engine half
    (MEC-67, optional tapping cost + cast-state marker) is **done**, so this
    is parser-only. Seed cards: Go Nuts!, Widow's Bite, HULK SMASH!,
    Atlantis Attacks, Murdock's Crusade.
  - **PAR-58 · Reflexive modal trigger wrapper.** Parse `you may pay <cost>.
    When you do, choose N —` as a `pay_cost_then` continuation whose payoff
    is a modal triggered ability, retaining RULE 603.11 stack/target order.
    The continuation plumbing (MEC-69, `enqueue_reflexive_trigger` +
    `then_trigger_modes`) is **done**, so this is parser-only. Seed cards:
    Voltstorm Angel,
    Hylda of the Icy Crown, Gorbag of Minas Morgul, Vision Synthezoid
    Avenger.
- **PAR-59 · Haunt-trigger modal wrapper (RULE 702.55).** Parse `when ~
  enters or the creature it haunts dies, choose N —` and the standalone
  `when the creature this card haunts dies` form. The haunt link/exile
  mechanic and event (MEC-70) are **done**, so this is parser-only. Seed
  cards: Orzhov Pontiff, Absolver
  Thrull, Belfry Spirit, Blind Hunter, Exhumer Thrull, Graven Dominator.

- **PAR-64 · Raid condition positional forms.** `you_attacked_this_turn` is
  now a real shared engine predicate, but the live probe still finds
  20 SOLO cards whose condition sits in an entry replacement, trigger wrapper,
  activation restriction, or `instead` override rather than the ordinary
  `if <cond>, <body>` gate. Measure each wrapper before widening it; the
  condition vocabulary is no longer the blocker. Seed cards: Rigging Runner,
  Bloodsoaked Champion, Alesha, Who Laughs at Fate, and Arrow Storm.

## MEC — Game mechanics

> No open tickets.
>
> New MEC tickets come from `scripts/commander_tail_report.py`'s bucket D
> (~132 Commander-legal cards; its signature labels name the *missing
> primitive*). Not filed, on purpose: the Attractions family (RULE 701.45
> Assemble, 701.51 Open an Attraction, 701.52 Roll to Visit Your Attractions)
> is a permanent non-goal in `DEFERRED.md`.

## PLR — Player management

- **PLR-9 · User accounts.** Login/signup (docs/04 PART 4), auth token
  storage + attachment to API/WebSocket calls, browser-refresh reconnect
  flow (docs/04 S1), and login/signup pages. Saved decks are unscoped until
  this exists — anyone hitting the API sees every deck. Also what actually
  closes the collision gap the PLR-4 client-token stub (`services/
  lobby.py`'s `client_token`, `Done_Backend.md` "Client-token identity
  stub") only covers halfway: that token is unsigned, client-trusted data —
  copy/clear/forge it and nothing notices — and a client that has never
  opened Profil still resolves purely by name, the original "two people
  sharing a name share a seat" collision. Fine for a LAN table, not for
  anything public.

## VIS — Visuals

- **VIS-4 · Chat / emotes at the table.**
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9.
- **VIS-9 · Accessibility** — alt-text on cards, tab navigation,
  high-contrast mode. docs/05 PART 10.
- **VIS-10 · Responsive/mobile layout** — only checked at desktop width.

> No Node/npm on this machine, so there is no JS linter/formatter/typecheck
> — but real-browser verification *is* available: Playwright (Python) lives
> in `backend/venv` and drives a real Chromium against the static frontend
> server plus a running backend. Use it for any non-trivial UI change
> instead of reading code and replaying API calls by hand.

## DB — Database

> **Gotcha:** adding a field to `Card` changes the schema hash, and
> `CardDatabase` wipes the whole app cache on mismatch. Recover offline with
> `python scripts/import_bulk.py --reseed-only` (rebuilds ~34k rows from
> `RawCardStore`). A targeted per-field backfill is never the right answer —
> the wipe is all-or-nothing.

## ANA — Deck analysis

- **ANA-1 · `POST /api/decks/{id}/analyze`.** Claude API integration, prompt
  templates, structured output parsing, caching (docs/02 UC2, docs/04 Phase
  6). `Deck.analysis_id` is reserved to link a saved deck to the result, but
  no `Analysis` model/table exists — design it alongside the endpoint rather
  than assuming the reserved field's shape is final.
- **ANA-2 · Narrative analysis UI** — win conditions, archetype, synergies,
  cohesion score, issues. Sits alongside the existing static/Bracket
  sub-tabs, not replacing them. Blocked on [ANA-1].
- **ANA-3 · Cache indicator** ("Analysis from X ago") for that LLM result.
  Blocked on [ANA-1].
