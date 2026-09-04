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

  - **PAR-32** — static `commander creatures you own have "<ability>"` /
    commander-matters anthem (24 SOLO). The wrapper + selector
    (`_COMMANDER_CREATURES_QUOTED_GRANT_RE` → `commander_creatures_you_own`)
    already existed; the residue is inner-body shapes
    `_quoted_ability_grant_effects` can't recurse. Done: **compound-event
    self-triggers** — "when ~ enters or leaves the battlefield, `<effect>`"
    → one `grant_triggered_ability` per event
    (`_quoted_ability_grant_effects_list`, `LEAVES_BATTLEFIELD` added to
    `_GRANTABLE_TRIGGER_EVENTS`), PARSER_VERSION 247, +1 Candlekeep Sage
    (the LTB half works end-to-end; the ETB half shares the engine's
    pre-existing granted-ETB-timing gap, same as any Dionus-style grant).
    **Static inner bodies** — anthem/lord (Inspiring Leader) — shipped via
    MEC-55 (`grant_static_ability` regrant primitive), PARSER_VERSION 248,
    +1. **Group-subject trigger regrant** — "whenever an artifact or
    creature you control dies …" (Agent of the Iron Throne) — shipped: a
    `group_condition` param on `grant_triggered_ability`, resolved per
    affected object by `effect_binder._build_group_ok` against the
    granted-to permanent (so "you control"/"other" re-scope); `_GROUP_
    SUBJECT_RE` widened to an "X or Y" main-type list (`type: [...]`, which
    `_build_group_ok` already ORs — this also fixed the *printed* form,
    silently mis-scoped as creature subtypes before). PARSER_VERSION 249,
    +2 (Agent of the Iron Throne / Nurturing Presence). **The "whenever ~
    attacks a player, if no opponent has more life than that player,
    `<payoff>`" cluster** — shipped (PARSER_VERSION 251, +16 with bonus):
    `_ATTACKED_PLAYER_LOWEST_LIFE_IF_RE` body-prefix intervening-if →
    `attacked_player_has_lowest_life` on the trigger, checked by
    `effect_binder.attacked_player_lowest_life_predicate` (shared with the
    re-granted path, ANDed in `_apply_layer_6_ability`); a
    `grant_self_subject_kw` handler for "it gains `<kw>` until end of turn"
    (Flaming Fist + ~10 self-attack-buff cards); `_PUMP_TARGET_SOURCE_
    POWER_RE` + `count_selector`'s `source_power` (Hardy Outlander); and
    `parse_effect_body`'s connector-split now carries `self_subject` across
    a clause that only re-references the source (Agent of the Shadow
    Thieves' "put a +1/+1 counter on ~. it gains …"). **Player-subject
    SPELL_CAST regrant** — shipped (PARSER_VERSION 252, +2): SPELL_CAST
    joined `_GRANTABLE_TRIGGER_EVENTS` / `_PLAYER_SUBJECT_GRANTED_EVENTS`
    so "Whenever **you** cast …" re-grants with "you" = the grantee's
    controller; a `_REGRANT_PASSTHROUGH_TRIGGER_KEYS` set carries firing-
    event gates (`spell_from_exile` — new `SPELL_CAST` event field +
    `effect_binder.regrant_trigger_gate_predicate`); `damage_spell_mv`
    handler ("deals damage equal to that spell's mana value"). Closes
    Passionate Archaeologist. **End-step blink + nontoken batch combat
    damage** — shipped (PARSER_VERSION 253, +3): `_BLINK_PLAIN_RE` gained
    a `tapped` target-state filter (`BlinkEffect.creature_filter`) →
    Far Traveler; `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` joined
    `_GRANTABLE_TRIGGER_EVENTS` / `_PLAYER_SUBJECT_GRANTED_EVENTS`, and the
    combat step now stamps `contributor_any_nontoken` so "1 or more
    **nontoken** creatures …" gates → Feywild Visitor.
    **End-step intervening-if conditions** — shipped (PARSER_VERSION 254,
    +2): two new per-turn `GameState` trackers (`damage_dealt_by_this_turn`
    /`creature_card_to_graveyard_this_turn`) + `static_conditions` kinds
    (`you_dealt_damage_this_turn_at_least`/`creature_card_to_graveyard_
    this_turn`), peeled off a phase-trigger body as `active_if` and carried
    through the re-grant path (`regrant_active_if_predicate`, ANDed in
    `_apply_layer_6_ability`) → Cloakwood Hermit / Dragon Cultist.
    **Cast-shares-type filter + event-player goad** — shipped
    (PARSER_VERSION 255, +2): `spell_shares_creature_type_with_source`
    trigger key + `effect_binder` predicate (compares the still-on-stack
    spell's subtypes with the source; `regrant_trigger_gate_predicate`
    carries it; `limit` → `once_per_turn` in the re-grant) → Folk Hero;
    `creature_that_player_controls` target kind + `is_player` on the
    aggregate combat-damage event + a `goad_that_player` handler → Popular
    Entertainer. **Permanent become-copy activated** — shipped
    (PARSER_VERSION 256, +1): `BecomeCopyPermanentEffect` / effect type
    `become_copy_permanent` (the non-reverting sibling of
    `become_copy_until_eot`, wrapping `RulesEngine.become_copy`) + a
    `become_copy_of_target` handler that picks the type by "until end of
    turn" wording → Shameless Charlatan (also gives Cursed Mirror an oracle
    route). **Master Chef's twin-body enters-with-counter grant** — shipped
    (PARSER_VERSION 257, +1, hand-authored — MEC-56): a new
    ``extra_etb_counter`` static (RULE 614.1 entry-counter *replacement*,
    the `grant_escape`/`grant_retrace` out-of-band idiom — consulted by
    `continuous.extra_etb_counters_for` from a new `RulesEngine._apply_
    granted_entry_counters`, called at both `_apply_entry_counters` call
    sites) granted twice onto every commander creature the controller owns
    — once `self_only` ("this creature enters with…"), once not ("other
    creatures you control enter with…"). The twin-quoted `"A" and "B"` body
    doesn't fit `_quoted_ability_grant_effects_list`'s single-inner-body
    recursion, so this is hand-authored rather than widening that grammar
    for a shape only this card uses. The `self_only` half inherits the same
    pre-existing granted-ETB-timing gap as Candlekeep Sage's ETB half (a
    grant onto an object isn't computed until *after* that object is
    already on the battlefield, so it can't affect its own entry) — the
    "other creatures" half has no such gap (the granting commander creature
    is already on the battlefield with its grant settled) and is the half
    that actually matters at the table. **Scion of Halaster's granted
    "first draw each turn" replacement** — shipped (PARSER_VERSION 258, +1,
    hand-authored — MEC-57): a new `first_draw_look_two` `ReplacementEffect`
    (gated on a new per-turn `GameState.first_draw_replaced_this_turn`
    tracker, distinct from the existing per-*draw-step* `first_in_draw_
    step` flag `_steal_non_first_draw_replacement`/Notion Thief already
    reads), granted the same `grant_static_ability` `static_specs` way as
    MEC-55/56 — `continuous._apply_layer_6_ability` now also recognises a
    nested spec whose type resolves to a `ReplacementEffect` rather than a
    `StaticAbility` and files it onto the new `GameObject._granted_
    replacement_effects`, read by `RulesEngine._all_replacement_effects`
    alongside a permanent's own printed ones — the general mechanism this
    unlocks for any future "X have '`<replacement>`'" card, not just this
    one. Which of the two looked-at cards is binned is non-interactive
    (always the second, `_discard_instead_of_non_first_draw_replacement`'s
    own "auto-chosen, no chooser in MVP" precedent). **Tavern Brawler's
    impulse-draw + pump-from-exiled-mv granted trigger** — shipped
    (PARSER_VERSION 259, +1, hand-authored — MEC-58): a two-clause granted
    STEP_BEGIN/upkeep trigger composing two existing primitives rather than
    a new one — `impulsive_draw` (`RulesEngine.exile_with_play_permission`)
    now also seeds `GameContext.created_objects` with the card it exiled
    (purely additive; no existing card reads it), and `PumpEffect` gained
    `amount_from_created_object_mana_value` to read that seeded card's mana
    value for the "+X/+0" (deliberately power-only, unlike `amount_from_
    trigger_event`/`amount_from_count_selector` which set both stats).
    `GameContext.exile_with_play_permission` had to start returning the
    exiled objects (was ``-> None``, discarding them) for any of this to be
    reachable. **Haunted One's becomes-tapped tribal pump** — shipped
    (PARSER_VERSION 260, +1, hand-authored — MEC-59): a granted `TAPPED`
    trigger (RULE 603.2, already grantable-shaped — self-subject,
    `instance_id`-keyed, same as every other RULE 603.1 object-subject
    grant) whose pump uses a new `PumpEffect` selector `self_and_shared_
    creature_type_you_control` — self plus every *other* creature the same
    controller controls whose printed subtypes overlap the source's own
    *live* subtypes (RULE 205.3g), computed at resolve time rather than a
    fixed list so it re-scopes correctly per affected commander creature.
    Left (each a distinct mini-project — hand-author + MEC as needed):
    Acolyte of Bahamut's per-turn-first subtype cost reduction; Dungeon
    Delver (dungeon-room trigger doubling — MEC); Noble Heritage
    (per-opponent protection + interactive per-player — MEC).
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
    PARSER_VERSION 238, +9). Left: `enters tapped. as it enters, choose a
    color` (#8), `if it's neither day nor night, it becomes day as ~
    enters` (#10).
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
  - **PAR-44** — static permission / prohibition (`you may play lands from
    your graveyard` #9, `a deck can have any number of cards named ~` #10 —
    a deckbuilding clause, claim-without-spec).
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

> **(none open.)** MEC-47/49/51/51b/52/53/54/55 all closed
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
