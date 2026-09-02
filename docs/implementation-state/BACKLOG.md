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

> **(none open.)** ENG-31 (parametric keyword *grants*, PARSER_VERSION
> 128), ENG-33 (villainous / vote option bodies, 129–132) and ENG-32
> (Waterbend, 131) — the three engine primitives PAR-29's keyword-action
> handlers needed — have all shipped; see `Done_Backend.md`. The residual
> per-card grammar around them is **PAR-30**, under `## PAR` below.

## PAR — Parser

- **PAR-12 · The indefinite long tail (methodology pointer, not a closeable
  ticket).** Strategy, current coverage, and worked examples all live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) — not duplicated here. Two
  tracks: **basic mechanics** (generic shapes, worked by raw cache-wide
  yield) and **set-specific mechanics** (one expansion/precon's own
  signature keyword, worked deck-first against a saved deck's actual
  commander/product). As of 2026-08-28 the basic-mechanics track's easy
  big wins are **exhausted**: a fresh cache-wide `rank` top-N verified
  card-by-card with `parser_probe.py blocked` came back all-already-claimed
  (see `PARSER_LONG_TAIL.md`'s "verify before sizing … at scale" lesson —
  PAR-20, now closed, was the dated finding; its one concrete follow-up,
  the RULE 604.3 CDA-P/T handler, shipped at PARSER_VERSION 105). So the
  **deck-first set-specific track is the primary one now** — audit a real
  saved deck's card list rather than re-mining `rank`. Planechase
  (901)/Archenemy (904) plane/scheme card *bodies* (13/309 measured
  2026-08-04) are ordinary long-tail work with a known card list under
  this same pointer, not a distinct ticket — their trigger conditions are
  already recognized, only the bodies are exotic even by tail standards.
  (Reaching a Planechase/Archenemy/Vanguard table at all is wired up end
  to end already — see Done_Backend.md "PLR-13"; Vanguard's own avatar
  picker/text is a permanent non-goal, see the MEC callout below.)

  > **Ticket-id note:** every number from `PAR-1` through `PAR-28` is
  > already a real, shipped, cross-referenced ticket elsewhere in this
  > codebase (grep before reusing one — `PAR-14`, for one, is RULE 603.2's
  > once-per-turn trigger limiter, `Done_Backend.md`, nothing to do with
  > keywords). The only open parser ticket below is `PAR-30` (`PAR-29`'s parser trail — `PAR-29` itself is closed, all 24 keyword actions now have recognition; see `Done_Backend.md`).

- **PAR-30 · PAR-29's parser trail — remaining effect-body grammar for the
  RULE 701 keyword actions.** `PAR-29` and its three spun-off engine
  tickets (`ENG-31` parametric keyword grants, `ENG-32` Waterbend cost,
  `ENG-33` villainous/vote option-body primitives) are all closed — full
  per-mechanic narrative in `Done_Backend.md`. What stays UNMODELED here is
  **not the keyword action** — every one has recognition + an engine
  primitive — it's the ordinary effect-/outcome-body grammar *around* it,
  card by card. Open scope only below; cache-wide `parser_probe.py` SOLO
  counts. Sub-cluster progress lands in `Done_Backend.md` /
  `PARSER_LONG_TAIL.md` per PARSER_VERSION bump — keep this list to what is
  *still* open.

  - **Face a Villainous Choice (RULE 701.55) + reanimator-token residue.**
    Each remaining reanimator-token cluster card blocks on its *own*
    filter/quantifier/tail gap: **Anikthea** "non-aura enchantment card"
    filter; **Hour of Eternity / Midnight Ritual / Foggy Swamp Visions**
    "exile X target creature cards … for each card exiled this way, `<per-
    card body>`" (the `return_from_graveyard` X-count form landed v168 —
    `count_selector="source_x_paid"`; the *exile* form still needs the
    "for each … this way" `count_from_context` scaling on the follow-up);
    **Sauron the Necromancer / Sin** "create a
    tapped [and attacking] token"; **Back from the Brink** "…and pay its
    mana cost:" activation cost. Villainous option bodies still open: "you
    create a token that's a copy of that card" (**The Master** — needs
    `previous_targets` threaded through `_apply_effect_specs` in the APNAP
    sweep, plus its "choose an opponent with the most life" subject);
    "exile cards … until you exile a nonland card, then cast it" (Ensnared
    by the Mara); "that creature becomes a 1/1 and loses all abilities"
    (Hunted by The Family); "each opponent who lost 3+ life this turn"
    (Davros).

  - **Firebending (RULE ~702.189) grants residue.** Only the "whenever you
    waterbend / earthbend / firebend / airbend" bending-verb trigger row
    (Avatar Aang) is left — needs each bending primitive to fire an event
    first. (Fire Nation Cadets closed at PARSER_VERSION 157 — the self
    parametric-keyword-grant static + the v156 `subtype_in_graveyard`
    condition; see `Done_Backend.md`.)

  - **Waterbend (RULE 701.67) residue — parser grammar for the shared
    shapes is DONE; the rest are primitive-blocked singletons.** The
    optional-additional-cost-paid tracker (v155), the `subtype_in_graveyard`
    condition + `<subtype>_cards_in_your_graveyard` count-selector (v156/158),
    the self parametric-keyword grant (v157) and Katara's suffix condition
    (v158) all shipped; see `Done_Backend.md`. What's left is one distinct
    MEC-scale engine primitive per card, not loose parser ends:
    - **Ruinous Waterbending** — "if paid, whenever a creature dies this
      turn, you gain 1 life": a *player-scoped, this-turn floating
      triggered ability*. `CreateDelayedTriggerEffect` is step-based only
      (RULE 603.7 "at the beginning of the next end step"); an event-based
      "whenever X this turn" temporary trigger is unbuilt.
    - **Secret of Bloodbending** — "you control target opponent during
      their next combat phase / turn": the Mindslaver / Word of Command
      family (control another player's turn), unbuilt.
    - **Spirit Water Revival** — "if paid, `<effect>` **instead**": the
      additional-cost-paid *amount-override* branch (v155 shipped only the
      additive "if paid, extra effect" form), + "no maximum hand size for
      the rest of the game" static + graveyard-shuffle.
    - **"waterbend {X}"** mandatory additional cost (Crashing Wave, Foggy
      Swamp Visions, Waterbender's Restoration) — the printed cost carries
      no `{X}`, so nothing announces the X the body reads.
    - **Waterbending Lesson** — "discard a card unless you waterbend {N}":
      a resolve-time pay-or-discard whose cost is a waterbend.
    - **Water Tribe Rallier** — "look at the top N … reveal a creature card
      with power M or less … rest on the bottom in a random order" (a
      `look_top_select` reveal-filter variant).
    - **North Pole Patrol** `waterbend {N}, {T}` compound cost; **Ward—
      Waterbend {4}** (The Unagi); **Exhaust — Waterbend {3}: becomes an
      artifact creature …** (Invasion Submersible); the "whenever you
      waterbend / earthbend / firebend / airbend" bending-verb trigger
      (Avatar Aang — no bending events fire yet); plus cards blocked on
      unrelated clauses (Aang Swift Savior — airbend a *spell*; Katara
      Bending Prodigy — "her" pronoun; Waterbender Ascension — quest
      counters; Hama — alt-cast by waterbending; Aang's Iceberg — O-Ring).

  - **Collect Evidence / Forage / Blight activated-body residue.** Three
    sub-clusters shipped (see `Done_Backend.md`): the reflexive *targeted*
    "When you do, `<payoff>`" shape (v206 — `pay_cost_then.then_trigger`,
    RULE 603.11, +43 family); the exotic `{cost}, collect evidence N`
    activated-ability bodies (v207 — `_COST_LOOKS_REAL` keyword-action
    costs + `exile_attached` / `_DISCARD_THEN_IF_YOU_DO_RE` /
    `each_player_pay_or` scope-and-OR bodies, +13; Hedge Whisperer
    hand-authored); and Feed the Cycle's "forage" additional cast cost
    (v208, `additional_cost={"forage": True}`). What's left, each its own
    primitive:
    - **Tenth District Hero** — the second leveler body: "becomes a
      legendary creature named Mileva, the Stalwart … and gains 'Other
      creatures you control have indestructible'" (a become-legendary-
      renamed static + a granted anthem).
    - **Dynamic "collect evidence X"** — Incinerator of the Guilty (choose
      X as you collect; the payoff `~ deals X damage to each creature and
      planeswalker that player controls` also needs a group-damage
      selector scoped to the reflexive trigger's outer event-player).
      **Memory Vampire** — its reflexive half rides v206's `then_trigger`,
      but the card also needs "any number of target players each mill that
      many cards" (dynamic multi-target mill) and "cast target nonland
      card from a graveyard without paying its mana cost" (a new one-shot
      cast-from-graveyard-free primitive).
    - **Conspiracy Unraveler** — "you may collect evidence 10 **rather
      than pay the mana cost for spells you cast**": a battlefield
      permanent granting an alternative cost to *every* spell its
      controller casts. The cast path's `alt_cost` reads only a spell's
      *own* `AbilitySpec.alt_cost`, not an externally-granted one — needs
      a scan-the-battlefield-for-alt-cost-grants hook in `can_cast` /
      `_offer_cast` / `cast_spell`.
    - **Behold** — Molten Exhale (conditional-flash fused with a behold
      cost), Elven Passage ("you may behold an elf. If you do, untap that
      land."), the Champion cycle ("behold a `<type>` and exile it" + LTB
      return), Celestial Reunion ("behold 2 creatures of a chosen type").

  - **Clash (RULE 701.30) win-branch residue — parser grammar is DONE; 6
    primitive-blocked singletons remain.** Eight batches (v147–v154) worked
    the whole "if you win, `<body>`" seam and, along the way, unlocked **7
    general effect families** that a clash card merely sat inside (X-damage
    `_damage_x` +20; `skip_next_untap` "doesn't untap during its
    controller's next untap step" +51; `grant_protection` "from the colour
    of your choice" +17; `dig_until` "reveal from top until a `<type>`
    card" +9; `opponents_enchantments`/`_artifacts` destroy-all scope +1;
    `GainLifeEffect.amount_from_subject` "gain life equal to `<its / that
    creature's>` `<power/toughness>`" +14; `DealDamageEffect.recipient_
    subject` "deals N to that creature's controller" +10 — ~+124 total).
    The 6 cards left each need a **genuinely new engine primitive**, not
    parser grammar — file them as MEC-shaped work, not a parser section:
    **Hoarder's Greed** — a repeat-this-whole-process loop (the process is
    "lose 2 life, draw 2, clash"); **Broken Ambitions** — "counter target
    spell unless its controller pays `{X}`" (X = the counter spell's own
    announced X) *and* "that spell's controller mills 4" (`MillEffect`
    needs a `previous_subject_controller` recipient, the sibling of the
    damage/life-gain ones just shipped); **Whirlpool Whelm** — a bounce
    whose destination is *overridden* ("put that creature on top of its
    owner's library **instead**") on a win; **Captivating Glance** — an
    indefinite "gain control of enchanted creature" (a permanent
    control-change of an Aura's own host, no existing effect); **Pulling
    Teeth** / **Pollen Lullaby** — a "that player" referent carried from
    the clash win-branch's own target/opponent into the "otherwise" branch
    (or, for Pollen Lullaby, from the clashed opponent).

  - **Suspect (RULE 701.60) one-off shapes.** A genuine if/else *effect*
    primitive ("if `<cond>`, A. Otherwise, B." — two mutually exclusive
    bodies, not `ConditionalEffect`'s single-branch gate) for Agrus Kos;
    a "can't become `<designation>`" static-flag family + a `Conditional
    Effect` key reading a previous-subject's own `is_suspected` (Airtight
    Alibi); a bare cost-less mid-resolution "you may `<effect>`" wrapper
    (Deadly Complication); a designation-aware group-subject trigger filter
    "whenever 1 or more suspected creatures you control attack" (Clandestine
    Meddler).

  - **RULE 701.10 exchange-control / exchange-life residue** (parked here
    since PAR-29, not strictly a keyword action): a cross-target "shares a
    card/permanent type with it" legality predicate (Confusion in the Ranks,
    Daring Thief, Gauntlets of Chaos, Legerdemain, Role Reversal, Shifting
    Loyalties, The Trickster-God's Heist, ~7); the numeric-comparison
    sibling (Puca's Mischief, Spawnbroker); "you neither own nor control"
    target kind (Conjured Currency); a "nonlegendary" `creature_filter` key
    (Djinn of Infinite Deceits); "the `<X>` with the greatest mana value"
    dynamic selection (Cultural Exchange, Juxtapose); exchanging a **spell**
    on the stack (Perplexing Chimera, Sudden Substitution); a delayed triple
    exchange (Mirror Mirror); a pre-effect numeric-comparison gate (Psychic
    Transfer). Teams (Get a Life, RULE 810) is a permanent non-goal.

  - **Not gaps** (real handler verified action-by-action): Attach, Counter,
    Create, Destroy, Discard, Exile, Fight, Goad, Investigate, Mill,
    Regenerate, Scry, Search, Shuffle, Surveil, Tap/Untap, Transform/
    Convert, Proliferate, Monstrosity, Adapt, Amass, Manifest/Cloak,
    Manifest Dread, Venture, The Ring Tempts You, Connive, Discover,
    Explore, Populate, Bolster, Support, Suspect, Detain, Endure, Recruit,
    Collect Evidence, Forage, Behold, Learn, Incubate, Clash, Blight,
    Earthbend, Airbend, Vote, Face a Villainous Choice, Time Travel,
    Exchange Control, Exchange Life Totals — plus engine-action verbs with
    no oracle grammar (Activate/Cast/Play) and variant-subsystem ones
    (Planeswalk/Set in Motion/Abandon, Meld). Harness (701.64) / Heal
    (701.69) have ~0-3 cache cards and no handler yet — trivially small.
    Assemble (701.45) is out of the CR; Open an Attraction / Roll to Visit
    (701.51/52) are the Attractions non-goal.

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
  and `PARSER_LONG_TAIL.md`. Run cited: PARSER_VERSION 186, 2026-09-01.

  Bucket B (recurring effect-body / static templates, `extend-parser` loop):

  - **PAR-31** — loyalty `−N: you get an emblem with "<ability>"` (#35).
  - **PAR-32** — static `commander creatures you own have "<ability>"` /
    commander-matters anthem (#22).
  - **PAR-33** — Aura/Equipment grants a *quoted* ability
    (`enchanted/equipped creature has "…"`, `… gets +N/+N and has "…"`,
    `enchanted land has "…"`, `<cost>: regenerate enchanted creature`)
    (~#21+9+9+8).
  - **PAR-34** — tribal / state lord (`all slivers have "…"`, `each
    creature you control with a +1/+1 counter has trample`, Threshold
    `as long as <n>+ cards in your graveyard, ~ has/gets …`) (~#15+9+9).
  - **PAR-35** — casting-timing restriction (`cast this spell only during
    the declare attackers step and only if you've been attacked`,
    conditional flash `as though it had flash if you pay <cost> more`, the
    `… flash. if you cast it any time a sorcery couldn't …` templating)
    (~#14+9+9).
  - **PAR-36** — trigger-condition vocabulary (`whenever you draw your
    second card each turn`, `whenever ~ deals damage, you gain that much
    life`, `whenever ~ deals combat damage to a player, that player
    discards a card`, `whenever you cast a spell that targets ~`)
    (~#12+10+9+8).
  - **PAR-37** — modal `choose <n>. if you control a commander … choose
    both instead` + `choose <n>. you may choose the same mode more than
    once` (~#12+12; both currently reach Bucket A/B as wrapper headers —
    confirm they are genuinely unrecognised first).
  - **PAR-38** — `skip your draw step` drawback static (#12) + `at the
    beginning of your upkeep, ~ deals <n> damage to you` (#10).
  - **PAR-39** — old two-sentence O-Ring templating (`when ~ leaves the
    battlefield, return the exiled card to the battlefield under its
    owner's control`) (#12) — **reuse the PAR-30 Threaten/O-Ring cluster**.
  - **PAR-40** — `~ deals <n> damage to each creature and each player`
    symmetric selector (#11) + `~ deals <n> damage to target creature. if
    that creature would die this turn, exile it instead` damage rider (#11,
    reuse the exile-instead-of-death replacement) + `~ deals <n> damage to
    target creature with flying` modal body (#14).
  - **PAR-41** — additional cost `{X}` / from graveyard (`discard x
    cards` #10, `exile a creature card from your graveyard` #8).
  - **PAR-42** — conditional / dynamic enters-tapped & entry counters
    (`enters tapped unless a player has <n> or less life` #10, `enters
    tapped. as it enters, choose a color` #8, `with a +1/+1 counter for
    each color of mana spent to cast it` = Sunburst #9, `if it's neither
    day nor night, it becomes day as ~ enters` #10).
  - **PAR-43** — self CDA / `for each` P/T (`~'s power is equal to the
    number of creatures you control` #10, `~ gets +N/+N for each artifact
    you control` #10).
  - **PAR-44** — static permission / prohibition (`you may play lands from
    your graveyard` #9, `a deck can have any number of cards named ~` #10 —
    a deckbuilding clause, claim-without-spec).
  - **PAR-45** — ETB compound utility (`tap target creature an opponent
    controls and put a stun counter on it` #10, `as ~ enters, choose an
    opponent` #10, `target opponent loses <n> life and you gain <n> life`
    #8).
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

  - **PAR-54** — `Choose N. You may choose the same mode more than once.`
    (Fiery / Mystic / Righteous / Verdant / Wretched Confluence, Unite the
    Coalition). Needs repeatable-mode selection in the engine
    (`spell_modes` + `_modal_cast_actions` currently assume distinct
    picks); one `MODAL_HEADER_RE` variant + a `repeatable` modes flag +
    the engine offer. MEC-scale — file as MEC-50 if the engine half
    dominates.
  - **`Choose N. If <cond>, choose <more> instead.`** (Inscription of Ruin
    "if kicked … any number", Flame of Anor "if you control a wizard …",
    Let's Play a Game, Prophetic Titan, Depth Defiler) — the **existing
    "kicked … instead override" gap** (see the notable-gaps list in
    `CLAUDE.md` / this file's PAR-12 pointer); add these as its card list,
    don't open a new ticket.
  - **`Choose N. If this spell was cast using Teamwork, choose both
    instead.`** (Go Nuts!, Widow's Bite) — Teamwork is a Final Fantasy
    set-specific mechanic already listed **Not done** in
    `PARSER_LONG_TAIL.md`'s "Two tracks" table; Bucket C, deck-first.
  - **`… choose N that hasn't been chosen this turn —`** triggered-modal
    header (The Vision, Monument to Endurance, Galadriel Light of Valinor,
    Kimoyo Beads, Teval's Judgment, Wardens of the Cycle, Immard, Breeches)
    — needs the header variant **plus** per-object "modes already chosen"
    state that persists across the ability's firings. MEC-scale.
  - **reflexive / haunt-wrapped modal triggers** (Orzhov Pontiff "enters or
    the creature it haunts dies", Voltstorm Angel / Hylda / Gorbag "you may
    pay {cost}. when you do, choose one —", Vision Synthezoid Avenger) —
    fold into the reflexive-trigger and haunt work; not a modal-specific
    gap.

## MEC — Game mechanics

- **MEC-47 · Licid — a creature that turns itself into an Aura.** `{cost}:
  ~ loses this ability and becomes an Aura enchantment with enchant
  creature. Attach it to target creature. You may pay {cost} to end this
  effect.` (~12 Commander-legal cards, the whole Tempest Licid cycle +
  reprints — `scripts/commander_tail_report.py` Bucket D). Needs a
  creature↔Aura in-place state-change primitive (type line + attachment
  swapped on the *same* object, reversible), which no existing effect does
  — grep `game/effects.py` for `becomes`/attachment before building. Parser
  half: one `catalogue/handlers.py` activated-ability handler emitting it.
- **MEC-48 · Specialize (Duskmourn, ~RULE 702.166).** ~50 cache cards, the
  `PARSER_LONG_TAIL.md` "Two tracks" table's largest still-open
  set-specific mechanic. Needs the "exile the specialize card, it comes
  back as a colour-chosen copy / a sacrifice-timed token" effect (not yet
  built — see that table's row) plus the keyword-cost recognition. One
  batch: primitive + `catalogue/` handler + `PARSER_VERSION` bump.
- **MEC-49 · Per-turn damage-source attribution.** `whenever a creature
  dealt damage by ~ this turn dies, …` (Abattoir Ghoul, Baron Sengir,
  Blood Cultist, … ~28 Commander-legal cards). Needs a `GameState`
  per-turn map of "which permanents dealt damage to object X this turn"
  (cleared in cleanup) plus the RULE 603.1 trigger-condition filter that
  reads it. Check the Clash batch's `_damage`-family work
  (`Done_Backend.md`) for an adjacent tracker before building.

> **Permanent non-goals** (never to be built, not gaps): Stickers (RULE
> 123) and Attractions (RULE 717) — `gate.parse_oracle` classifies mentions
> of the former `NEVER_SUPPORTED`, a verdict kept out of both the coverage
> count and the backlog ranking. **Vanguard (RULE 902) beyond its already-
> shipped hand-size/life-total modifiers** — its ~107 avatars are a small,
> long-retired supplemental-product pool (not a real deck, no set is
> designed around it today), so neither a per-seat avatar picker (every
> seat just gets a random avatar — the modifiers apply regardless of which
> one) nor parser handlers for individual avatars' extra rules text will be
> built. Structurally enforced already, not just documented:
> `scripts/import_bulk.py`'s `_SKIP_LAYOUTS` drops the Scryfall `vanguard`
> layout from `cache/db/cards.db` entirely (0 of the 34,208 cached cards),
> so avatar text can never surface in `coverage_report.py`/
> `processing_list.py`'s ranking in the first place — the committed
> `services/variant_card_database.py` pool they live in instead is never
> read by either. `game/effect_binder.bind_from_catalogue` still binds
> whatever a general-purpose handler happens to already recognize when an
> avatar is actually boarded (RULE 902.2), same as any other unregistered
> card — that's ordinary runtime behavior, not scheduled work, and needs no
> special-casing to stay that way.

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
- **PLR-14 · Team variants (RULE 809/810/811).** Two-Headed Giant, Emperor
  and Grand Melee are the part of CR 8 that `models/game_format.py`
  deliberately doesn't model: unlike the RULE 9 variants (which add a card
  pool beside the game) these change the **turn structure itself** — a
  shared life total, two players taking one turn together, a "defending
  team" in combat, RULE 810.8's shared damage assignment. That's a turn-loop
  and combat project, not a format record. The seats it needs exist now (a
  table opens for up to four), so what's left is genuinely the turn loop;
  reaching it from the UI follows the same already-shipped format-picker
  pattern the RULE 9 variants use (Done_Backend.md "PLR-13").

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
