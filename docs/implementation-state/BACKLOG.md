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
    Worth's mass-graveyard-return / "destroy all creatures other than ~".

  - **Face a Villainous Choice (RULE 701.55) + reanimator-token residue.**
    Each remaining reanimator-token cluster card blocks on its *own*
    filter/quantifier/tail gap: **Anikthea** "non-aura enchantment card"
    filter; **God-Pharaoh's Gift / Offspring's Revenge** "It gains haste
    until end of turn." after a *create-token* antecedent — needs
    `GameContext.created_objects` (not `previous_targets`) threaded as the
    "it" referent (the ~55-card "create token … It gains haste" SOLO
    cluster, its own PAR item); **Hour of Eternity** "exile X target
    creature cards"; **Offspring's Revenge** "target red, white, or black
    creature card" colour filter; **Sauron the Necromancer / Sin** "create
    a tapped [and attacking] token"; **Back from the Brink** "…and pay its
    mana cost:" activation cost. Villainous option bodies still open: "you
    create a token that's a copy of that card" (**The Master** — needs
    `previous_targets` threaded through `_apply_effect_specs` in the APNAP
    sweep, plus its "choose an opponent with the most life" subject);
    "exile cards … until you exile a nonland card, then cast it" (Ensnared
    by the Mara); "that creature becomes a 1/1 and loses all abilities"
    (Hunted by The Family); "each opponent who lost 3+ life this turn"
    (Davros).

  - **Firebending (RULE ~702.189) grants residue.** **Fire Nation Cadets**
    ("~ has firebending N as long as there's a lesson card in your
    graveyard") — needs a self-keyword-grant static shape ("~ has
    `<keyword>` [as long as `<cond>`]", not parsed at all today) **and** a
    `static_conditions.py` "a lesson card in your graveyard" condition.
    Also the "whenever you waterbend / earthbend / firebend / airbend"
    bending-verb trigger row (Avatar Aang) — needs each bending primitive
    to fire an event first.

  - **Waterbend (RULE 701.67) residue.** ~18 of 28 cards still UNMODELED,
    each on its own gap: **"waterbend {X}"** additional cost
    (Crashing Wave, Foggy Swamp Visions, Waterbender's Restoration — needs
    the printed cost to trigger an {X} announcement it doesn't); **"you
    may waterbend {N}" + "if this spell's additional cost was paid"**
    (Katara Seeking Revenge, Ruinous Waterbending, Secret of Bloodbending,
    Spirit Water Revival — a Kicker-shaped *optional additional cost paid*
    tracker, unbuilt); **"discard a card unless you waterbend {N}"** body
    (Waterbending Lesson); **Water Tribe Rallier**'s "look at the top N …
    reveal a creature card with power M or less … put the rest on the
    bottom in a random order" (a `look_top_select` reveal-filter variant);
    **North Pole Patrol**'s `waterbend {N}, {T}` compound cost + "{T}:
    untap another target permanent"; **Ward—Waterbend {4}** (The Unagi);
    **Exhaust — Waterbend {3}: becomes an artifact creature …** (Invasion
    Submersible); the "whenever you waterbend / earthbend / firebend /
    airbend" bending-verb trigger (Avatar Aang — no bending events fire
    yet). Plus cards blocked on unrelated clauses: Aang, Swift Savior
    (airbend a *spell*), Katara, Bending Prodigy ("her" pronoun),
    Waterbender Ascension (quest counters), Hama (alt-cast by
    waterbending), Aang's Iceberg (O-Ring clause).

  - **"Create a token …. It gains haste until end of turn." tail (~55
    SOLO cache-wide).** The singular-pronoun previous-subject pump family
    resolves "it gains `<kw>` until end of turn" against `previous_targets`,
    but a *create-token* antecedent leaves the pronoun pointing at
    `GameContext.created_objects` instead — needs that threaded as the "it"
    referent in `segmenter`'s connector-split loop (and `PumpEffect.
    previous_subject` to fall back to it). Would also close the
    God-Pharaoh's Gift / Offspring's Revenge reanimator-token members.

  - **Threaten / "it gains haste" tails residue.** Still open in the
    `gain_control_until_eot` family: the *targeted-opponent mass* form
    ("gain control of all creatures target opponent controls until end of
    turn. untap those creatures. they gain haste …" — Broadcast Takeover,
    Call for Aid — needs a targeted-player-scoped mass selector); the
    richer haste clause ("until end of turn, it gains haste and `<X>`" /
    "it gains haste and `<kw>`" — Furnace Reins, Loki's Scepter, Flayer of
    Loyalties, Firbolg Flutist); the multi-event O-Ring trigger forms
    ("enters or transforms into ~" — Brutal Cathar; "enters and at the
    beginning of your first main phase" — Crack in Time); the **old
    two-sentence Oblivion Ring** templating ("exile another target nonland
    permanent." + a separate "When ~ leaves the battlefield, return the
    exiled card…"); and card-specific after-tails (Goatnap "if that
    creature is a Goat", Awaken the Sleeper "if it's equipped", Driftgloom
    Coyote / Food Coma).

  - **Incubate (RULE 701.53) dynamic amount residue.** Still open: "…where
    X is **its power**" — a dying creature's own last-known power (Bloated
    Processor, Furnace Gremlin); "…X is **its mana value**" of a
    just-exiled permanent read by *its controller* (Excise the Imperfect);
    "X is the number of creatures **exiled this way**" (Sunfall);
    "incubate N **that many times**" / "incubate N **X times**" — a
    search/count-driven repeat (Phyrexian Incubator, Progenitor Exarch).
    Plain "incubate N" cards blocked on unrelated surrounding grammar:
    Assimilate Essence ("if they do, you incubate 2" reflexive), Tiller of
    Flesh (trigger condition), Traumatic Revelation ("if you don't"),
    Searing Barb ("if it's a creature, it can't block").

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

  - **Clash (RULE 701.30) win-branch residue.** ~22 cache clash cards stay
    UNMODELED on ordinary effect-grammar in their "if you win" branch, each
    needing a distinct body handler: a "repeat this process" loop
    primitive, mass "untap all Forests you control", "return this card to
    its owner's hand" self-bounce as a split clause, "~ deals N damage to
    that creature's controller", "that player `<verb>s`", "protection from
    the color of your choice", … — none of it clash-specific. Also open:
    making "clash with an opponent" a *referent-transparent* interstitial
    in the connector-split loop so a "`<main effect on target>`. clash. if
    you win, `<that creature …>`" card keeps its pronoun chain across the
    clash sentence.

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
