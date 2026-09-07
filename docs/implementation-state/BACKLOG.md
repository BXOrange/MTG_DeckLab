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

> **(none open.)**

## PAR — Parser

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
  > parser ticket id is `PAR-54` (`PAR-31…PAR-53` are the Commander-legal
  > tail clusters below).

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
  [`.claude/plans/analysiere-den-unmodelled-cardpool-und-crystalline-blanket.md`]
  and `PARSER_LONG_TAIL.md`. Run cited: PARSER_VERSION 186, 2026-09-01. Every ticket shall be completed end to end without leaving residue before moving to the next ticket.

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
    file as PAR-54… when their batch comes up; not enumerated further here
    to keep the list to the first wave.
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
    conditional riders to a `teamwork_paid` condition; the optional tapping
    cost and cast-state marker are **MEC-67**. Seed cards: Go Nuts!, Widow's
    Bite, HULK SMASH!, Atlantis Attacks, Murdock's Crusade.
  - **PAR-58 · Reflexive modal trigger wrapper.** Parse `you may pay <cost>.
    When you do, choose N —` as a `pay_cost_then` continuation whose payoff
    is a modal triggered ability, retaining RULE 603.11 stack/target order;
    the continuation plumbing is **MEC-69**. Seed cards: Voltstorm Angel,
    Hylda of the Icy Crown, Gorbag of Minas Morgul, Vision Synthezoid
    Avenger.
  - **PAR-59 · Haunt-trigger modal wrapper (RULE 702.55).** Parse `when ~
    enters or the creature it haunts dies, choose N —` and the standalone
    `when the creature this card haunts dies` form. The haunt link/exile
    mechanic and event are **MEC-70**. Seed cards: Orzhov Pontiff, Absolver
    Thrull, Belfry Spirit, Blind Hunter, Exhumer Thrull, Graven Dominator.

- **PAR-60 · Secrets of Strixhaven Commander decks — saved-deck playability
  (set-specific track, PAR-12).** Make all five *Secrets of Strixhaven*
  saved decks (Witherbloom Pestilence, Silverquill Influence, Quandrix
  Unlimited, Prismari Artistry, Lorehold Spirit) fully playable —
  every card MODELED by the oracle parser or AUTHORED in
  `game/ability_catalogue/`. Baseline (2026-09-07, PARSER_VERSION 277):
  ~232/433 covered, ~190 unique uncovered cards. Worked deck-first in
  waves (`scripts/deck_coverage.py --uncovered "<deck>"`), building the
  minimal parser handler / engine primitive per cluster and hand-authoring
  the singleton tail. Recurring clusters spotted at triage, each gets its
  own PAR/MEC as it comes up:
  - **magecraft** (RULE 702.153) trigger recognition — Archmage Emeritus,
    Veyran, Harmonic Prodigy, Storm-Kiln Artist-shaped (Prismari + others).
  - **learn / Lesson sideboard** (STX) — parser recognition only; Lessons
    are a non-goal for the sideboard fetch, model the "draw a card or"
    branch.
  - **the Impetus curse cycle** (Ghoulish/Martial/Parasitic Impetus) —
    Aura on any creature, combat-damage rider redirecting the reward to
    the Aura's controller.
  - **`{X}` hydra bodies** with ETB `X`/doubling interactions — Primordial
    Hydra, Hydroid Krasis, Lifeblood Hydra, Goldvein Hydra, Benevolent
    Hydra (Quandrix).
  - **fractal / +1/+1-counter-matters** payoffs (Quandrix) — mostly
    existing primitives, verify.
  - **"the first time … each turn" iteration** — Determined Iteration,
    Expressive Iteration-shaped (Prismari).
  Progress + per-wave log: session scratchpad `secrets_of_strixhaven_plan.md`.
  Fully-shipped waves (1, 5, 8) are filed in `Done_Backend.md` under
  "Secrets of Strixhaven"; only waves with open follow-ups remain below.
  Open follow-ups by wave:
  - wave 2: **magecraft** (RULE 702.153) recognition — `segmenter._CAST_
    SPELL_TRIGGER_RE` widened with optional `(?:or copy )?`, PARSER_VERSION
    278, +12 cache. Only the "cast" half binds (no spell-copy event bus).
    Veyran / Harmonic Prodigy still blocked on "that ability triggers an
    additional time" — an ability-doubling primitive, own future MEC.
  - wave 3: `segmenter._ATTACHED_MULTI_EVENT_RE` — "whenever enchanted/
    equipped creature **attacks or blocks**, …" (PARSER_VERSION 279).
    `LoseLifeEffect.selector="attached_permanent_controller"`. Silverquill's
    Impetus cycle (Parasitic / Martial / Ghoulish Impetus) hand-`AUTHORED`
    in `entries_018.py`. Still open, tracked here:
    - bare **"its controller loses N life"** as an effect body — needs a
      previous-subject-controller (Vapor Snag / Countersquall / Undermine /
      Hideous End: "its" = the spell/creature the prior clause hit) vs.
      attached-subject (the Impetus/Curse Auras: "its" = enchanted creature)
      split, so it doesn't mis-model the counterspell family. ~13 SOLO on
      `whenever enchanted creature attacks` alone plus the whole
      counter-with-life-loss cluster.
    - **Martial Impetus's** real "attacking one of your opponents" attacker
      selector (currently hand-authored with the looser
      `other_attacking_creatures`).
    - (`you scry N` as an effect body — closed by wave 13. Still open: a
      compound trigger body that isn't split on ". then " — Overwhelmed
      Apprentice's "each opponent mills 2 cards. then you scry 2.")
  - wave 4: "when ~ dies, [you gain life and] draw cards equal to its
    power/toughness" (Lifeblood Hydra) + "create a number of tapped Treasure
    tokens equal to its power" (Goldvein Hydra). New
    `DrawCardEffect.amount_from_subject` / `CreateTokenEffect.count_from_
    subject`. PARSER_VERSION 280. Quandrix hydras still open (Primordial
    Hydra's upkeep counter-double closed by wave 9):
    - **Hydroid Krasis** — "when you cast this spell, you gain **half X**
      life and draw **half X** cards, round down" (a cast trigger reading
      half the announced {X}).
    - **Benevolent Hydra** — "that many **plus one** +1/+1 counters instead"
      counter-add replacement + a counter-move activated ability.
  - wave 6: **"target nonbasic land"** target kind (+ `nonbasic_land_you_
    dont_control`) and a "…onto the battlefield tapped" tail on the
    controller-searches-basic-land follow-up. PARSER_VERSION 282, +~16
    cache (Fulminator Mage / Wasteland / … + White Orchid Phantom). Still
    open: the "an opponent controls. **each player** / **that land's
    controller** searches their library for a basic land" multi-search
    tails (Field of Ruin, Demolition Field, Magmatic Hellkite — the last
    also "with a stun counter on it").
  - wave 9: "**double the number of [+1/+1] counters on** <~ / target
    creature / each creature you control / it>" — `double_counters_on_
    target` effect grew a `mode` + `kind` filter. PARSER_VERSION 285, +12
    cache (Primordial Hydra in-deck + Kalonian Hydra / Dragonsguard Elite /
    Growth Curve / Bristly Bill …). Open: Vorel's "target artifact,
    creature, or land" union kind; "each of those creatures" post-distribute
    tail (Biogenic Upgrade, Court of Garenbrig).
  - wave 10: modal-mode sub-clauses blocking Charm/Command spells —
    "target player creates a <named> token" (`CreateTokenEffect.creators=
    "target"` + player `target_kind`) and "target player draws N cards,
    then discards M cards" (`_TARGET_PLAYER_LOOT_RE`). PARSER_VERSION 286,
    +2 cache — unblocks **Prismari Command**. (Prismari Command, Quandrix
    Charm, Quandrix Command, Lorehold Charm and Witherbloom Command are all
    now playable — see wave 11 and wave 12.)
  - wave 11: "**target creature [you control] has base power and toughness
    N/N until end of turn**" — `_BASE_PT_UNTIL_EOT_RE` widened to a RULE 115
    target (`grant_until` needed no change). PARSER_VERSION 287, +7 cache —
    unblocks **Quandrix Charm**. Separate PAR-60 shapes, still open: the
    compound "loses all abilities and becomes a <colour> <type> with base
    P/T" (Turn to Frog / Snakeform / Ovinize) and the front-loaded "until
    end of turn, … and gains <kw>" (Creeperhulk).
  - wave 12: the three remaining modal Charm/Command spells hand-`AUTHORED`
    wholesale in `entries_018.py` (no PARSER_VERSION change) — **Quandrix
    Command**, **Lorehold Charm**, **Witherbloom Command**. New engine
    pieces: `ShuffleTargetGraveyardCardsIntoLibraryEffect`
    ("shuffle_target_graveyard_cards_into_library", + a `graveyard_to_
    library` `CHOOSE_OBJECT_ACTIONS` entry) for Quandrix Command's
    "target player shuffles up to three target cards…" mode; a
    `noncreature_nonland_permanent` target kind (`nonland_permanent` minus
    creatures) for Witherbloom Command's mode 2. Lorehold Charm's
    graveyard-reanimate mode reused the existing
    `graveyard_artifact_or_creature` kind + `max_mana_value`. Documented
    simplifications: Lorehold Charm mode 1's "nontoken" narrowing (not
    expressible on `SacrificeEffect.what`); Witherbloom Command mode 1's
    "you return a land card" modeled as a `graveyard_land` target in the
    controller's own graveyard.
  - wave 13: two small parser widenings (PARSER_VERSION 288 → 289, 0
    regressed). (a) "**[then] you scry N**" as an effect body —
    `handlers.scry_or_surveil`'s regex gained an optional leading `you `
    (Psychic Impetus, Clockwork Droid; ~2 cache). (b) "**<subtype> spells
    you cast cost {N} less/more to cast**" — `static_handlers`'s
    `_SPELL_COST_TAX_YOU_CAST_RE` handler routes a single curated
    creature/Aura/Equipment/Arcane subtype word to ``spell_subtype``
    (`continuous.cost_reduction_for` already resolved it via `has_subtype`);
    fail-closed on groupings ("historic"/"commander"). ~17 SOLO — the
    Banneret/Warchief tribal-discount cycle + **Transcendent Envoy**
    [Silverquill deck]. Coverage 14,268 → 14,285.
  - wave 7: RULE 603.3f **"1 or more … creatures … die"** batch-death
    triggers — modeled as a per-object DIES group trigger, claimed only
    with a "this ability triggers only once each turn." body. PARSER_VERSION
    283, +6 cache (Morbid Opportunist in-deck + Sengir Connoisseur / Vraan /
    Dramatic Finale / Ghoulish Procession / Homicide Investigator). Still
    open: a **real batch-aggregate death event** (one firing per RULE
    603.3f batch) for the un-limited variants (Great Fierce Bee, Vengeful
    Townsfolk, Blood Spatter Analysis) and the "1 or more creatures **died
    this turn**" end-step check (Feast of the Victorious Dead) — an
    engine/MEC primitive, and it would also let the batch-ETB "1 or more
    creatures … enter" family (Tocasia's Welcome, Bygone Bishop) fold in.
  - wave 14: "**whenever you cast a <colour> spell, …**" —
    `segmenter._CAST_SPELL_TRIGGER_RE`'s dispatch gained a colour branch
    (`_CAST_SPELL_COLOR_WORDS` → `effect_binder`'s already-shipped
    `cast_of_color` key, the Runaway Steam-Kin predicate). PARSER_VERSION
    289 → 290, ~11 SOLO + **Balefire Liege** [Lorehold deck] (Cinder
    Pyromancer, Emberstrike Duo, …). Still open for Lorehold: the
    **"whenever 1 or more cards leave your graveyard"** batch trigger
    (Quintorius, Field Historian + Quintorius, History Chaser) — needs the
    graveyard-exit batch event in **MEC-78**.
  - wave 15: "**<subject> gets +x/+x [and gains <kw>] until end of turn**"
    — new `handlers._pump_x` (ahead of the digits-only `pump` row) emits
    the `"x"` power/toughness sentinel `RulesEngine._substitute_x` already
    rewrites to `GameObject.x_paid`. PARSER_VERSION 290 → 291, ~6 SOLO:
    +**Tyvar's Stand** and **Primal Might** [Quandrix deck], Untamed Might.
    A "where X is <board count>" tail stays fail-closed — that's the
    `amount_from_count_selector` "+X/+X where X is <devotion / land types /
    card types>" family (~82 SOLO cache-wide, its own future PAR).
  - wave 16: "**this spell costs {N} less to cast for each <type> card in
    your graveyard**" — new `static_handlers._SELF_COST_REDUCTION_GY_RE`
    emits `affects="self"` + a `per` graveyard-count selector
    `continuous.count_selector` already resolves (+ a new
    `instant_or_sorcery_cards_in_your_graveyard`). Single-type / "instant
    and sorcery" only; "cave"/"artifact and/or creature"/"…in exile and in
    your graveyard" fail-closed. PARSER_VERSION 291 → 292, ~7 SOLO
    (Ghoultree, Molderhulk, Cryptic Serpent, Tolarian Terror, …). **Furygale
    Flocking** [Prismari deck] now blocked on only one clause: "for each
    opponent, create 2 3/3 …elemental tokens with flying that attack that
    opponent this turn if able" (a per-opponent forced-attacking token
    creator — its own PAR shape).
  - wave 17: 'create a … creature token with **"when ~ dies, you gain N
    life."**' — the STX Pest token's own printed death trigger. The
    inline-create-token regex gained a quoted-ability tail alternative;
    `CreateTokenEffect.token_dies_gain_life` binds a `dies`→`gain_life`
    `TriggeredAbility` onto each created token (the triggered-ability
    sibling of `grant_self_anthem`). PARSER_VERSION 292 → 293, ~5 SOLO
    (Hunt for Specimens, Professor of Zoomancy, …). Narrows the Witherbloom
    Pest cards to their *other* remaining clauses, each its own PAR shape:
    **"attacking Pests you control get +1/+0 and have <kw>"** (Blight
    Mound, Feral Appetite — a subtype-scoped attacking-only anthem);
    **"attacking Pests you control get +1/+0 and have <kw>"** (Blight
    Mound, Feral Appetite — a subtype-scoped attacking-only anthem; still
    open).
  - wave 18: a phase trigger's leading RULE 603.4 intervening-if "**if you
    control no <subtype>[s]** / **if you don't control a <subtype> [creature]
    token**, …" (`segmenter._YOU_CONTROL_NO_SUBTYPE_IF_RE`, curated
    `_CONTROL_NO_SUBTYPE_WORDS`) → the trigger's `active_if` as
    `control_count` `max=0` over `creatures_you_control_of_type_<subtype>`.
    The "…token" qualifier is a documented simplification. PARSER_VERSION
    293 → 294, +**Ophiomancer** and **Pest Rescuer** [Witherbloom deck].
    Still open in this family: "if you control no creatures **with
    decayed**" (Jadar — a keyword-scoped count, not a subtype) and "no
    `<subtype>` **other than ~**" (Thopter Assembly).
  - wave 19: "**Attacking <subtype> you control get/have …**" (Blight
    Mound, Dire Fleet Neckbreaker, Elderfang Venom, Crossway
    Troublemakers). `static_handlers._scope` strips a leading "attacking"
    into `_Scope.attacking`; `_scope_params` folds it into an
    `attacking_creatures_you_control[_of_type_<subtype>]` `affects`
    selector, with new branches in `continuous`'s anthem resolver.
    PARSER_VERSION 294 → 295, +**Blight Mound** [Witherbloom deck]. Feral
    Appetite now blocked on only its `{1}{G}` activated ability ("exile
    target card from a graveyard. if a creature card is exiled this way,
    create a Pest …" — a conditional-on-what-was-exiled create-token).
  - wave 20: "**<creature> deals damage to itself equal to its power**"
    (Justice Strike / Inner Struggle / Wrack with Madness / Repentance /
    Kiku's Shadow on a target; Wave of Reckoning / Solar Blaze as an "each
    creature" mass form). `DamageEqualToPowerEffect` gained a `to_self`
    flag — dealer == recipient (no second target), and the mass form has
    no dealer target at all (every creature reads its *own* power).
    PARSER_VERSION 296 → 297, 9 SOLO cache-wide, +**Wave of Reckoning**
    [Lorehold deck].
  - wave 21: "**you and target opponent each draw N cards**" (Secret
    Rendezvous, Sky Crier, Loran of the Third Path, Farsight Adept, Flumph,
    Love Song of Night and Day). A `handlers.py` row emits two `draw`
    `EffectSpec`s — one untargeted (source's controller), one
    `target_kind="opponent"` — in that order. PARSER_VERSION 297 → 298,
    6 SOLO cache-wide, +**Secret Rendezvous** [Silverquill + Lorehold decks].

## MEC — Game mechanics

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
