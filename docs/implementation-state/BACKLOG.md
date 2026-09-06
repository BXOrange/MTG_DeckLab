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
  - **PAR-57 · Per-turn exhausted triggered modes.** Parse `choose N that
    hasn't been chosen [this turn] —` and carry an ability-stable mode key;
    mode-history state and trigger chooser filtering are **MEC-68**. Seed
    cards: The Vision, Monument to Endurance, Galadriel, Light of Valinor,
    Kimoyo Beads, Teval's Judgment, Wardens of the Cycle, Immard.
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

## MEC — Game mechanics

- **MEC-76 · Dance — remaining card-resolution packages.**
  Hand-author and execute the smaller, still distinct bodies after the shared
  primitives above: **Return of the Wildspeaker** (non-Human greatest-power
  modal draw/pump), **Mass of Mysteries** (temporary myriad grant),
  **Slithermuse** (leave-battlefield opponent choice and hand-size delta
  draw), and **Impulsivity** (graveyard instant/sorcery free cast plus a
  one-spell graveyard-to-exile replacement). Each needs an end-to-end
  contract; none may be marked covered solely by catalogue registration.


- **MEC-67 · Teamwork optional additional cost (RULE 702.194).** Offer a
  cast variant that taps any number of creatures the caster controls whose
  total power meets the printed threshold, records `teamwork_paid` on the
  spell, and fires the corresponding cast/payment signals. It must coexist
  with ordinary mana, Kicker, Convoke, targets, and cast-time mode selection.
  PAR-56 owns parser reachability; the remaining Teamwork rider families are
  separately measured PAR-12 work, not silently claimed here.

- **MEC-68 · Persistent per-object modal history.** Store a mode set keyed
  by the permanent/ability and current turn, clear it at turn boundary, and
  exclude those entries from each later `trigger_mode` offer. Record only
  after a mode is legally chosen; modes from different abilities on the same
  object must not collide. PAR-57 owns its header grammar.

- **MEC-69 · Modal reflexive continuations (RULE 603.11).** Extend the
  existing `pay_cost_then` path so a successful optional payment can enqueue
  a modal triggered payoff, then present its mode choice before its targets
  and resolve it as an independent stack object. Must not collapse `When you
  do` into an ordinary same-resolution effect.

- **MEC-70 · Haunt (RULE 702.55).** Implement the death-triggered exile/link
  to a chosen creature, retain the haunt relationship while that creature
  remains on the battlefield, and emit the linked creature's death event for
  the exiled card's haunt abilities. Cover the activated `exile ~ haunting
  target creature` variant as well. PAR-59 owns the parser forms; unrelated
  Haunt card bodies remain normal parser-tail work.

- **MEC-64 · Suspend's own "activate from hand" special action (RULE
  702.62a, first ability).** Only the *second/third* abilities are
  implemented — tick down a time counter each upkeep, then free-cast at zero
  (`SuspendUpkeepEffect`, `game/effects.py`; `_has_suspend`/
  `_collect_suspend_triggers`, `game/rules/triggers_mixin.py`) — plus
  Delay's own redirect-with-counters shortcut (`counter_spell`'s
  `suspend_time_counters` param, `game/rules/misc_mixin.py`). There is no
  action anywhere that offers a hand card's own printed "Suspend N—cost" as
  a player-choosable alternative to casting it (checked
  `legal_actions_mixin.py`/`casting_mixin.py`/`activation_mixin.py` —
  nothing implements it). Explicitly flagged as a known gap in
  `game/ability_catalogue/entries_014.py` (Delay's own comment). Ordinary
  hard-casting of a card that happens to have Suspend is unaffected (e.g.
  Ancestral Vision casts fine at its own printed — free — cost); this is
  purely about the alternative "exile it with N time counters instead of
  casting it" action. Build it the way Escape/Flashback add their own
  alternate cast-cost path in `game/engine/casting_mixin.py`
  (`_escape_cost`/`_flashback_cost` + their `legal_actions` offers): parse/
  read the printed "Suspend N—{cost}" cost, add a special action that pays
  it, exiles the card with N time counters, and sets whatever bookkeeping
  `_has_suspend`/the upkeep tick-down already expects to find. Found while
  fixing the back-face mana-cost bug (2026-09-05, `models/card.py`
  `back_face()`) — not the same bug, just adjacent code read during that
  investigation; no regression, just a pre-existing unimplemented action.

> MEC-47/49/51/51b/52/53/54/55/56/57/58/59/60/61/62 all closed
> (`Done_Backend.md`); MEC-48's Specialize-rider tail is parked in
> [DEFERRED.md](DEFERRED.md).

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
