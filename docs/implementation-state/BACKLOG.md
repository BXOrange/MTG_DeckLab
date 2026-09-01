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

  - **Vote (RULE 701.38) outcome bodies.** 3+-option votes (Council
    Guardian — WUBRG protection vote); "vote for a nonland permanent / a
    graveyard card" then "exile/return each with the most votes" (Council's
    Judgment, Custodi Squire — a *targeted-tally* shape, no named options);
    a per-player subject carried across "and" in a per-vote body (Capital
    Punishment — deliberately fail-closed); "planeswalk / chaos ensues" and
    "the Ring tempts you" outcome bodies (Path of the Animist/Enigma,
    Galadriel); "you choose how each player votes" (Illusion of Choice);
    Expropriate's extra-turn / gain-control per-vote outcome; Magister of
    Worth's mass-graveyard-return branch (its "destroy all creatures other
    than ~" branch is done, v163).

  - **Face a Villainous Choice (RULE 701.55) + reanimator-token residue.**
    Each remaining reanimator-token cluster card blocks on its *own*
    filter/quantifier/tail gap: **Anikthea** "non-aura enchantment card"
    filter; **Hour of Eternity** "exile X target creature cards";
    **Offspring's Revenge** "target red, white, or black creature card"
    colour filter *and* its "It gains haste until end of turn." after a
    create-token antecedent (the referent half shipped v146 — a
    `create_token`/`copy_permanent` spec now announces the "it"; only the
    colour filter is left); **Sauron the Necromancer / Sin** "create a
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

  - **Threaten / "it gains haste" tails residue.** Still open in the
    `gain_control_until_eot` family: the *targeted-opponent mass* form
    ("gain control of all creatures target opponent controls until end of
    turn. untap those creatures. they gain haste …" — Broadcast Takeover,
    Call for Aid — needs a targeted-player-scoped mass selector); the
    richer haste clause — now only the *quoted granted-ability* form
    ("it gains haste and \"whenever ~ deals combat damage …\"" — Furnace
    Reins, Loki's Scepter, Flayer of Loyalties): the plain second-keyword
    form ("gains haste and myriad until end of turn") and the "**another
    target creature you control**" selector both parse as of
    PARSER_VERSION 161 (see `Done_Backend.md`); Firbolg Flutist is still
    blocked on its own gain-control-then-untap tail; the multi-event O-Ring
    trigger forms
    ("enters or transforms into ~" — Brutal Cathar; "enters and at the
    beginning of your first main phase" — Crack in Time); the **old
    two-sentence Oblivion Ring** templating ("exile another target nonland
    permanent." + a separate "When ~ leaves the battlefield, return the
    exiled card…"); and card-specific after-tails (Goatnap "if that
    creature is a Goat", Awaken the Sleeper "if it's equipped", Driftgloom
    Coyote / Food Coma).

  - **Incubate (RULE 701.53) residue — the dynamic-amount grammar is
    DONE.** "…where X is its power" (v160), "its controller incubates X,
    where X is its mana value" + "…the number of creatures exiled this
    way" (v162 — `creators="previous_target_controller"`, `count_from_
    subject`, the `GameContext.objects_exiled_this_way` accumulator) all
    shipped; see `Done_Backend.md`. What's left is **not** dynamic-amount
    grammar — each is its own separate primitive:
    - **Phyrexian Incubator** "incubate N **that many times**" — a
      search-result count that must survive a `pending_choice` suspension
      boundary (the search opens a choice; RULE 608.2 parks the rest of
      the effect list; the count has to be threaded through the resume).
    - **Progenitor Exarch** "incubate N **X times**" — the repeat count is
      the source permanent's own `x_paid` ({X}{X} creature), not this
      resolution's announced X; also blocked on its "{T}: transform target
      Incubator token you control" activated ability.
    - Plain "incubate N" cards blocked on unrelated surrounding grammar:
      Assimilate Essence ("counter … unless its controller pays {N}. if
      they do, …" reflexive), Tiller of Flesh ("whenever you cast a spell
      that targets 1 or more permanents" trigger condition), Traumatic
      Revelation ("if you don't, …" else-branch), Searing Barb ("if it's a
      creature, it can't block this turn" on a damage target).

  - **Collect Evidence / Forage / Blight activated-body residue.** Exotic
    `{cost}, collect evidence N:` bodies (Hedge Whisperer land-animation,
    Polygraph Orb edict, Tenth District Hero class-up); Gristle Glutton's
    `{T}, Blight 1: discard a card. If you do, draw a card.` and Spiral into
    Solitude's three-part `{1}{W}, Blight 1, Sacrifice ~:` body; *targeted*
    "when you do, `<targeted payoff>`" that `pay_cost_then` can't resolve
    off-stack (Sample Collector, Memory Vampire, Curious Forager, Warren
    Torchmaster); dynamic "collect evidence X" (Incinerator of the Guilty);
    "collect evidence N / forage / behold `<quality>` **rather than pay the
    mana cost**" alt-cast forms (Conspiracy Unraveler, Feed the Cycle);
    Behold's Molten Exhale (conditional-flash fused with a behold cost),
    Elven Passage ("you may behold an elf. If you do, untap that land."),
    the Champion cycle ("behold a `<type>` and exile it" + LTB return),
    Celestial Reunion ("behold 2 creatures of a chosen type").

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

## MEC — Game mechanics

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

(none open)

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
