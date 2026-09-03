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
> handlers needed — have all shipped; see `Done_Backend.md`. PAR-30
> (PAR-29's parser trail) is closed too; the six cards its
> reanimator-token / villainous-choice residue still couldn't reach are
> each blocked on a distinct **engine** primitive now, tracked as
> **MEC-52** under `## MEC` below.

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

  > **Ticket-id note:** every number from `PAR-1` through `PAR-30` is
  > already a real, shipped, cross-referenced ticket elsewhere in this
  > codebase (grep before reusing one — `PAR-14`, for one, is RULE 603.2's
  > once-per-turn trigger limiter, `Done_Backend.md`, nothing to do with
  > keywords; `PAR-30` was `PAR-29`'s parser trail, closed PARSER_VERSION
  > 216 — all 24 RULE 701 keyword actions have recognition + an engine
  > primitive, and its last residue moved to `MEC-52`). The first free
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
  - **PAR-45** — ETB compound utility (`as ~ enters, choose an opponent`
    #10, `target opponent loses <n> life and you gain <n> life` #8). (The
    `tap target creature and put a stun counter on it` half closed at
    PARSER_VERSION 213 — `handlers.tap_and_stun` + RULE 122.1c stun-counter
    skip-untap in `RulesEngine.set_tapped`; see `Done_Backend.md`.)
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
    the engine offer. MEC-scale — file as the next free MEC-* if the
    engine half dominates.
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

- **MEC-48 · Specialize riders (Alchemy — digital keyword).** The core
  Specialize keyword shipped in MEC-48 (v223): parser recognition of a bare
  "Specialize {cost}" line, `effect_binder._specialize_activated_ability`
  (a real sorcery-speed "{cost}, Discard a card" activated ability →
  `SpecializeEffect`, a `GameObject.is_specialized` designation +
  `EventType.SPECIALIZED`; the per-colour face swap is a documented
  simplification, no face data in the seed), and the "specializes" trigger
  verb — see `Done_Backend.md`. **Still open:** a handful of cards print
  the keyword *with a rules rider on the same line*, held UNMODELED by
  `segmenter._SPECIALIZE_WITH_RIDER_RE` rather than greedily over-claimed —
  each is a small activated-ability-modifier follow-up:
  - "Specialize {5}. This ability costs {3} less to activate if there are
    2+ instant/sorcery cards in your graveyard." (Imoen) — a conditional
    activation-cost reduction.
  - "Specialize {2}. Activate only if a player has 13 or less life." /
    "…if you control 6 or more lands." (Shadowheart, Lukamina) — an
    `ACTIVATION_CONDITION_MARKER` gated on a `static_conditions` predicate
    (needs a `player_life_at_most` kind).
  - "Specialize {6}. You may also activate this ability if ~ is in your
    graveyard." (Karlach) — an alternate activation zone on an activated
    ability (`ActivationCost.graveyard_zone` as an *also*, not a
    replacement).
- **MEC-51 · Control another player's turn (or a part of it — e.g. a
  combat phase).** "You control target opponent during their next turn."
  (Mindslaver, Sorin Markov's `−7`, Emrakul, the Promised End, Worst
  Fears) / "…during their next combat phase." (Secret of Bloodbending) /
  "…play with your hand revealed and you control that player's choices
  this turn." (Word of Command-adjacent). The engine has no "one player
  makes another player's decisions for a bounded window" machinery — this
  is a real spread of touch-points, not one hook:
  - a `GameState` mapping `{controlled_player_id → (controller_id,
    scope, armed_turn)}` with `scope ∈ {"turn", "combat"}` and a small
    state machine (`TemporaryPlayerTrigger`-style: `waiting` → `active` at
    the controlled player's next matching window → expire), so it
    survives `GameState.clone` as plain data;
  - **priority / actions**: `GameSession.apply_action(action, actor_id=…)`
    and `GameEngine.legal_actions(perspective=…)` must let the controller
    act *as* the controlled seat while active — the multiplayer actor
    validation in `_dispatch` already keys on a per-seat id, so this is a
    redirect there, not a new path;
  - **interactive choices**: a `pending_choice` raised for the controlled
    player must be re-addressed to the controller (its `player_id`),
    including nested sub-choices (search, mode, target) — the single
    largest sub-task;
  - **turn-based actions**: declare-attackers / declare-blockers /
    discard-to-hand-size / mulligan-adjacent are taken by the controller;
  - **the fenced-off bits** (RULE 720.1): the controlled player still
    can't be made to concede, and effects that would end the game or
    reveal/keep their hidden info follow 720.x — a documented-simplification
    boundary is acceptable for a first cut (model the decision routing,
    note the 720.x edge cases as unmodeled).
  Closes **Secret of Bloodbending** (the last Waterbend-residue card,
  everything else shipped — see `Done_Backend.md`), and unblocks the
  Mindslaver family cache-wide. One batch: the state + machine + the
  routing hooks + a hand-authored `EffectSpec("control_player", {"scope":
  …})` (bespoke enough per card that the parser handler can come later).

- **MEC-52 · Reanimator-token & villainous-choice residue — engine
  primitives.** The tail of PAR-29's keyword trail (PAR-30, closed
  PARSER_VERSION 216). The *parser* side of each is one small handler once
  the primitive below exists — this is engine work, not oracle grammar.
  Shipped so far: the graveyard-exile-copy piece at v216 (Anikthea, Hour of
  Eternity, Midnight Ritual); **Sauron, the Necromancer** at v217 (a
  RULE 603.4 `DelayedTrigger.condition` "…unless ~ is your Ring-bearer" +
  the "tapped and attacking" / "with `<keyword>`" copy-tail widenings);
  **Davros, Dalek Creator** at v218 (`GameState.life_lost_this_turn`, a
  `ConditionalEffect` `opponent_lost_life_this_turn_at_least` key +
  `FaceVillainousChoiceEffect.subject_min_life_lost`); **The Master,
  Gallifrey's End** (hand-authored, no bump — `FaceVillainousChoiceEffect`
  `subject="opponent_with_most_life"` + `capture_previous` so a villainous
  option's "copy of that card" resolves after the choice is answered). See
  `Done_Backend.md` "Reanimator-token residue". What's left:
  - **Back from the Brink** — an activated ability whose cost is "exile a
    creature card from your graveyard **and pay its mana cost**": a
    *variable* cost priced off a chosen object (the exiled card's own mana
    cost, unknown until the graveyard pick). `game/costs.py` + the
    activation flow have no "pick-then-price" cost. "Activate only as a
    sorcery" already parses.
  - **Hunted by The Family** — per-target villainous: "choose up to four
    target creatures you don't control. For each of them, **that creature's
    controller** faces a villainous choice — …". Needs
    `FaceVillainousChoiceEffect` `subject="previous_target_controller"`
    iterated once per chosen target, and option bodies that act on the
    *creature*: "becomes a 1/1 white Human creature and loses all
    abilities" (`base_pt` + `remove_all_abilities` + colour/subtype set,
    permanent not EOT) / "you create a token that's a copy of it" —
    `handlers._villainous_option_specs` currently rejects any spec whose
    `target_kind` isn't `None`/`"player"`.
  - **Ensnared by the Mara** — villainous option bodies: "exile cards from
    the top of their library until they exile a nonland card, then you may
    cast that card without paying its mana cost" (`dig_until` exists —
    make it villainous-option-legal) and "…exiles the top four cards of
    their library and ~ **deals damage equal to the total mana value of
    those exiled cards** to that player" — needs a "damage = summed MV of
    the cards exiled this way" amount source.

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
