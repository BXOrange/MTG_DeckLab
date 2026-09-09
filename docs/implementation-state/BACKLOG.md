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
  `if_else`). What remains is retiring the fusions, and the reason that is a
  separate piece of work is measured rather than assumed:

  - **80 of the 84 fusions have every part already registered as a standalone
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
    Plowshares (referent amount *and* referent recipient), Nature's Claim
    (recipient only), Feed the Swarm (amount only). What remains is the
    batch work: each migration is rewrite-the-producer, delete-the-class,
    drop-the-`isa`-row, with the card's own test asserting the number.
  - **Only two effects are wired to the operand vocabulary so far**
    (`gain_life`, `lose_life`, via `GameEffect._operand_player` on the two
    existing fallback chains). Each further batch needs its effects wired the
    same way — a one-line intercept per fallback chain, not a new parameter.
  - **Re-derive the 84 before using it as a target.** Inspection found the
    count over-states: `wheel`/`wheel_of_fortune` are `for_each` with a fixed
    draw, not `bind` (nothing is measured), and several `seq` rows (`haunt`,
    `taxed_draw`, `blink`) are single rules concepts rather than welded pairs.
  - **Exit:** an operand-side referent vocabulary; the re-derived fusion list
    retired in batches, `isa.fusions_retired_by(<op>)` shrinking with it.

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
  retirement remains) → **PAR-62**
  (clause grammar) → **PAR-63** (slot grammars).

  This ticket holds only what is not in those six:

  - **Cherry-pick `81c3320` onto this branch first** — its 44-line
    "clause-tree grammar tier" conclusion in `09_` and its
    `subgrammars.SELF_SUBJECT_PREFIX`. It lives on the unmerged
    `arch/grammar-tier-prototype`, so a recorded architectural negative result
    is currently invisible to anyone working here and will keep being
    re-proposed. It rejected an *adjacent* proposal (a clause-tier for
    handler-count reduction) and does not refute the above, but its
    instruction — measure a family's genuinely-duplicated vs genuinely-distinct
    rows before touching it — binds.
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

- **PAR-62 · Clause grammar with residue (`14_` S4).** Rewrite
  `segmenter.parse_effect_body` as recursive descent over the connectives
  measured in `13_` section 5.2 (`if` 16.5%, `you may` 13.8%, `then` 8.3%,
  `for each` 5.9%, `instead` 3.4%, …), replacing the all-or-nothing
  `fullmatch` with a **residue** mechanism: a rule may claim part of a clause
  and hand the rest on, instead of one unmodelable fragment discarding every
  sibling that parsed.
  Fix the two standing positional gaps here — mid-body `you may` (a known gap
  named in `09_`; `_peel_optional` strips only a *leading* one) and
  `subgrammars.UP_TO_ONE`, hardcoded to N=1.
  **Highest-risk ticket in the chain** — every currently-MODELED card is
  re-derived through it, and there is no partial rollout. Mitigation: the full
  suite plus a full-cache before/after coverage diff. **The atom layer it
  needs now exists** — ENG-34/35/36 are closed and ENG-37's composition nodes
  are shipped, so recursive descent has something to descend into; ENG-37's
  remaining half (retiring the fused types) shrinks what this has to route
  around but does not block it.
  **Exit:** coverage does not regress; templates-per-blocked-card (**1.12
  today**) falls.

- **PAR-63 · Cross-module sub-grammar reuse (`14_` S5).** `static_handlers.py`
  (3,943 lines) imports five names from `subgrammars` and **not** `TARGET`;
  `replacements.py` imports **none**; the same five-entry colour dict is
  declared three times (`handlers.py`, `replacements.py`, `subgrammars.py`).
  `PERMANENT_TYPE_WORD` has zero uses despite a docstring describing the
  duplication it exists to remove.
  Scope is *cross-module* reuse only. **Do not re-run `81c3320`'s experiment**
  on the damage/destroy/exile rows — it already showed their count is driven by
  genuine semantic and parse-context variety, not redundant surface grammar.
  Measure any family the way that commit did before touching it.


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
  > parser ticket id is **`PAR-62`** (checked 2026-09-08): `PAR-31…PAR-53` are
  > the Commander-legal tail clusters below, `PAR-54`/`PAR-55`/`PAR-57`/`PAR-60`
  > are shipped and written up in `Done_Backend.md`, `PAR-56`/`PAR-58`/`PAR-59`
  > are open below, and `PAR-61` is the grammar-restructure decision above.

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
    `enchanted land has "…"`) (~#21+9+9). The `<cost>: regenerate
    enchanted creature` shape shipped at PARSER_VERSION 236
    (`_REGENERATE_ATTACHED_RE` → `RegenerateEffect`'s existing
    `attached_permanent` mode, +14 — Regeneration / Gaea's Embrace / Dark
    Privilege / Serpent Skin).
  - **PAR-34** — tribal / state lord. Done: `each creature you control
    with a +1/+1 counter on it has <keyword>` (`_GROUP_COUNTER_GRANT_RE` +
    `has_counter_kind` in `_SELECTOR_KEYS`, PARSER_VERSION 237, +18 — the
    Abzan outlast cycle); the Odyssey **Threshold** phrasing ("Threshold —
    As long as N or more cards **are in** your graveyard, …") now
    normalises + parses (+1 real card so far — the rest of that cluster is
    blocked on **quoted-ability** conditional bodies). Left: `all slivers
    have "…"` (~#13 — a group-scoped **quoted-ability** grant, recursively
    parsed) and the Threshold quoted-ability bodies (~#25 — same
    quoted-ability-grant machinery, wrapped in the `active_if` gate).
  - **PAR-35** — casting-timing restriction (`cast this spell only during
    the declare attackers step and only if you've been attacked`,
    conditional flash `as though it had flash if you pay <cost> more`, the
    `… flash. if you cast it any time a sorcery couldn't …` templating)
    (~#14+9+9).
  - **PAR-36** — trigger-condition vocabulary. Done: `whenever ~ deals
    damage, you gain that much life` (`gain_life_from_trigger_amount` +
    `GainLifeEffect.amount_from_trigger_event`, PARSER_VERSION 231, +17);
    `…discards a card at random` (`RulesEngine.discard_random` +
    `DiscardEffect.random`, PARSER_VERSION 233, +23). Left: `whenever you
    draw your second card each turn` (~#12 — shares with PAR-48),
    `…discards **that many** cards` reading the DAMAGE amount (Dreamstealer
    / Needle Specter — a `DiscardEffect.count_from_trigger_event`),
    `whenever you cast a spell that targets ~` (~#8).
  - **PAR-37** — modal `choose <n>. if you control a commander … choose
    both instead` + `choose <n>. you may choose the same mode more than
    once` (~#12+12; both currently reach Bucket A/B as wrapper headers —
    confirm they are genuinely unrecognised first).
  - **PAR-38** — residue only. The bare `skip your draw step` static and
    the bare `~ deals <n> damage to you` body both shipped at
    PARSER_VERSION 229 (`skip_step` oracle route; `damage_selector`'s
    `"you" → "controller"`; +22 — `Done_Backend.md`). What's left: the
    upkeep-damage **riders** — `~ deals <n> damage to you for each <X>`
    (Black Market Tycoon — needs a count-selector) and `~ deals <n> damage
    to you unless you pay <cost>` (Force of Nature / Minion of Tevesh Szat
    — a self-scoped `unless you pay` branch); plus `skip your draw step
    this turn` as a conditional "if you do" tail (Elfhame Sanctuary).
  - **PAR-39** — old two-sentence O-Ring templating (`when ~ leaves the
    battlefield, return the exiled card to the battlefield under its
    owner's control`) (#12) — **reuse the PAR-30 Threaten/O-Ring cluster**.
  - **PAR-41** — additional cost `{X}` / from graveyard. Done: `exile N
    [<type>] cards from your graveyard` (`ActivationCost.exile_from_
    graveyard_filter` + `_can_pay_/_pay_additional_cast_cost` wiring,
    PARSER_VERSION 234, +9 — Cobbled Lancer / Skaab family). Left: `discard
    x cards` and `exile x [creature] cards from your graveyard` — both need
    an **X-scaled additional cost** (the `additional_cost` fields carry a
    fixed int / the `pay_life` `"x"` sentinel, no general X-scaled
    non-mana-cost path yet).
  - **PAR-42** — conditional / dynamic enters-tapped & entry counters.
    Done: `enters tapped unless a player has <n> or less life` (the
    Innistrad slow-land life cycle — `lands.py`'s `unless_life` kind,
    PARSER_VERSION 230, +10); `~ enters with a +1/+1 counter on it for
    each color of mana spent to cast it` = **Sunburst** (`counters.py`'s
    `_SUNBURST_ENTRY_COUNTERS_RE` + `colors_spent_scale` in
    `_apply_entry_counters`, reading `GameObject.colors_spent_to_cast`,
    PARSER_VERSION 238, +9); `enters tapped. as it enters, choose a color`
    (the Thriving lands — PARSER_VERSION 267, +16 including the Gate cycle).
    Left: `if it's neither day nor night, it becomes day as ~ enters` (#10).
  - **PAR-43** — self CDA / `for each` P/T. The **single-characteristic
    CDA** — `~'s power is equal to the number of <X>` — shipped at
    PARSER_VERSION 235 (`_PT_CDA_SINGLE_RE` → a `pt_cda` spec with only
    `power_count` / `toughness_count`; the layer-7a pass already applied
    them independently; +12), for the same `_PT_CDA_SELECTORS` whitelist as
    the "power and toughness" form. The `~ gets +N/+N for each <X>`
    standing self-anthem form has its general handler
    (`_SELF_ANTHEM_FOR_EACH_RE`, PARSER_VERSION 228, +14) but only for the
    "for each <X>" quantities that already have a
    `continuous.count_selector`; the remaining tail (~120 SOLO, ~40
    distinct selectors — "Equipment you control" board-wide, "oil counter
    on it", "aura attached to it", "experience counter you have",
    per-subtype "other <type> you control", …) is one new
    `count_selector` per phrase in `continuous.py`, plus the **Aura** form
    (`enchanted creature gets +N/+N for each <X>` — `affects=
    "attached_permanent"` instead of `"self"`). See `Done_Backend.md`.
  - **PAR-44** — static permission / prohibition. The graveyard-land side is
    now closed for the Muldrotha-shaped permanent-type permission: the shared
    graveyard grant tracks one use for each permanent type, including a land
    play, and resets at untap. The remaining `a deck can have any number of
    cards named ~` #10 is a deckbuilding clause, claim-without-spec.
  - **PAR-45** — ETB compound utility. Left: `as ~ enters, choose an
    opponent` (#10). Closed: `target opponent loses <n> life and you gain
    <n> life` (the Blood Artist / Zulaport drain family — `lose_life`'s
    `who` alternation gained `target opponent` → `target_kind: "opponent"`,
    PARSER_VERSION 232, +34; the "and you gain" clause rides the existing
    `gain_life` row via the connector split). The `tap target creature and
    put a stun counter on it` half closed at PARSER_VERSION 213
    (`handlers.tap_and_stun` + RULE 122.1c stun-counter skip-untap in
    `RulesEngine.set_tapped`; see `Done_Backend.md`.)
  - **PAR-46** — cost reduction `for each creature card in your graveyard`
    (#9) and the Party count-selector (see PAR-50).
  - **PAR-47** — `<cost>,<cost>: put a charge counter on ~` + its
    remove-a-charge-counter spend clause (#14).
  - **PAR-48** — `whenever you draw your second card each turn, put a
    +N/+N counter on ~` (#12; Marvel/Ravnica "second card" trigger — folds
    into PAR-36's vocabulary work if taken together).
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
  header/engine support is missing). The triggered-modal wrapper half is
  done — `_split_triggered_modal_block` recognises its trigger via
  `segment_line` as of PARSER_VERSION 187 (Elder Gargaroth / Ojutai
  Exemplars / Etherwrought Page / Cosmogrand Zenith / Ferocification / Appa,
  +8 cache). What is left, ~26 Commander-legal cards in five shapes:

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

## MEC — Game mechanics

> `scripts/commander_tail_report.py`'s bucket D routes ~132 Commander-legal
> cards here. Its signature labels name the *missing primitive* rather than a
> ticket id, and ENG-34 re-pointed the ones that are missing **instructions**
> at `game/isa.py`, so the report's routing and the ISA are one ground truth.
>
> The six below are ENG-34's **CR-versus-engine diff**, produced
> systematically (`scripts/isa_report.py`) rather than discovered
> card-by-card: ISA instructions the Comprehensive Rules define that this
> engine has no realisation of at all. They are deliberately small and
> mechanical — `14_` §7 predicted exactly that, because the historical `MEC`
> stream was largely composition gaps wearing a mechanic's name.
>
> Not filed, on purpose: the Attractions family (RULE 701.45 Assemble,
> 701.51 Open an Attraction, 701.52 Roll to Visit Your Attractions) is a
> permanent non-goal in `DEFERRED.md`.

- **MEC-75 · Rolling a die (RULE 706).** No dice subsystem exists at all —
  `game/ability_catalogue/entries_006.py`'s Vrondiss entry says so in as many
  words ("the dice-roll clause is skipped entirely — this engine has no
  dice-rolling subsystem at all") and creates a vanilla token instead. Needs
  a `roll_die` primitive (agent, amount), a `DICE_ROLLED` event for the
  "whenever you roll one or more dice" trigger family, and the RULE 706.3
  ignore-lowest/highest riders. Sibling of `flip_coin` (RULE 705), which is
  already a primitive — copy its shape.
  > While here: several catalogue comments cite **`RULE 706` for copying**
  > (Clever Impersonator, `commander_cards.py`'s become-copy note). Copying
  > is RULE **707** in the current CR; 706 is Rolling a Die. Those citations
  > are stale, not wrong-in-spirit — fix them in the same pass so the new
  > `roll_die` work does not collide with them.

- **MEC-76 · Fateseal (RULE 701.29).** Absent. Scry's opponent-facing twin
  (look at the top N of *target opponent's* library, put any number on the
  bottom) — `scry`/`surveil` are both primitives, so this is the same shape
  with the agent and the patient's owner split apart, which is precisely the
  ISA's `agent`/`patient` frame distinction.

- **MEC-77 · Meld (RULE 701.42).** Absent as a primitive; `meld` exists only
  as a `Card.layout` string. Needs the pair-exile-and-return-as-one-permanent
  zone change plus the melded permanent's own back-face identity.

- **MEC-78 · Heal (RULE 701.69).** Absent. A recent keyword action (remove N
  damage / -1/-1 counters) with no engine realisation; the counter half is
  `remove_counter`, so scope is the damage-marking half plus the keyword.

- **MEC-79 · Harness (RULE 701.64).** Absent. (Grep hits on "harness" are the
  card *Fractal Harness*, not the keyword action.)

- **MEC-80 · Triple (RULE 701.11).** Absent, though `double` (RULE 701.10) is
  a primitive. Small by construction — the same amount-scaling operation at a
  different factor, which is the ISA's point: one operation, an `amount`
  role, not two registry rows.

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
