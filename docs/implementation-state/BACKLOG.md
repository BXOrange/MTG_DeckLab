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

## PAR — Parser

- **PAR-1 · Cross-target indirect referents.** Run Away Together's "Choose
  two target creatures controlled by different players. Return those
  creatures…" — the two-sentence "choose target(s) [+constraint]. Verb those
  [referent]s" shape has no recognition at all, though
  `ReturnToHandEffect` already accepts `distinct_controllers`. The
  single-sentence form *is* claimed for `destroy`/`exile`.
- **PAR-2 · Compound target-kind unions.** Price of Betrayal's "target
  artifact, creature, planeswalker, **or opponent**" — a player alongside
  three permanent types. Wider than the shipped
  `RemoveCountersEffect.max_count` shape, which already covers plain
  "target permanent"/"target creature".
- **PAR-3 · Non-creature group scopes.** `static_handlers._scope` only
  claims *creature* scopes, so every anthem/keyword-grant/quoted-grant
  family fails closed on "Other **enchantments** have '…'" (Aura Flux),
  "**Artifacts** you control get …". **Parser-side only** — the layer engine
  already has `artifacts_you_control`/`permanents_you_control`/
  `nonland_permanents_you_control`/`all_permanents`/`all_lands`. Keep the
  `_NONCREATURE_TYPES` block-list for the *anthem* family only (a "+N/+N"
  clause really is creature-only).
- **PAR-4 · "As ~ enters, choose a *basic land* type."** (RULE 601.2b) Needs
  its own option list in `RulesEngine._offer_enter_choices`; the creature-
  type and colour siblings are the only two shapes today. Blocks Realmwright
  and A-Thran Portal, whose type-grant halves are otherwise modeled.
- **PAR-5 · Hexproof-from-`<quality>` collapses to blanket hexproof.** RULE
  702.11b "Hexproof from red" is aliased onto the plain `hexproof` slug
  (`FLAG`-shaped, not `QUALITY`-shaped like `Protection`), so the scope is
  lost. Overprotective, never rules-illegal. Fix: give `Hexproof` a
  `QUALITY` shape. `parser/oracle/catalogue/keywords.py`'s `_ALIASES`.
- **PAR-6 · RULE 702.16n/p's "This effect doesn't remove this Aura." tail.**
  Leaves six of the eight protection-from-chosen-colour Auras UNMODELED
  even though the grant itself is modeled. The engine side this was blocked
  on has shipped (`RulesEngine._revalidate_attachments`, RULE 704.5m/n now
  re-checked every SBA pass, not just on the host leaving) — an Aura that
  grants "protection from `<colour>`" and doesn't carry this exemption would
  now genuinely detach itself the next SBA pass, so this is real parser
  work, not a no-op to skip.
- **PAR-7 · Kicker `{X}`'s own paid-X variant.** Emblazoned Golem, 1 card.
- **PAR-8 · Granting Cycling to other cards.** "Each card in your hand has
  cycling {2}" — a static-grant shape, not keyword recognition.
- **PAR-9 · Generic Cycling execution for unregistered cards.** The
  `discard_self` primitive exists; binding a bare oracle-recognized
  "cycling" spec into a real activatable ability is hand-authored per-card.
- **PAR-10 · Jin-Gitaxias-style compound activation condition.** "…and only
  if you have seven or more cards in hand" stacked on sorcery-speed timing;
  the whole clause fails closed rather than dropping the second condition.
- **PAR-14 · "This ability triggers only once each turn."** RULE 603.1's
  once-per-turn limiter, in both its printed spellings — the trailing
  sentence ("…put a +1/+1 counter on this creature. **This ability triggers
  only once each turn.**", Chance-Met Elves/Prudent Fateseer) and the
  in-condition one ("whenever you surveil **for the first time each turn**",
  Whispering Snitch). **182 cards** mention one, and every one of them fails
  the coverage gate as a whole today, however ordinary the rest of the card
  is — which is what makes this a ranked ticket rather than tail work: it's
  a *qualifier* blocking otherwise-modeled cards, not an unmodeled effect.
  Found while closing the scry/surveil trigger family (2026-07-28), where it
  is the single biggest blocker: 5 of those 25 cards are MODELED, and the
  limiter is why two of the near misses aren't.
  Needs a genuine new mechanism, not just a parser handler — a per-turn
  fired-count on the `TriggeredAbility` (reset at cleanup, RULE 514.2's
  neighbourhood) plus a `trigger["limit"]` the segmenter can emit. Grep
  first: nothing in `game/effects.py` counts firings per turn today
  (`GameState.stats` counts *game*-wide, and `temp_*` flags are cleared
  rather than counted), so this really is new — but check again before
  building, per the batch-discipline rule.
- **PAR-15 · "Any number of target `<X>`" targeting.** RULE 115.1a's
  "up to N" only ever generalizes today to a *literal* N (`TargetSpec.
  count`/`optional`) — "any number of" needs a freely-chosen, practically
  unbounded count instead, with the effect body applying per target the same
  "loop over the whole list" way `DestroyEffect`/`ExileEffect` already do,
  not `GrantCombatRestrictionEffect`/`AttachEffect`-shaped effects that
  currently only ever read `targets[0]` (grep before reusing one of those
  families for this — several silently drop every target past the first).
  **64 cached cards**, 0 modeled today — a genuinely new, sizeable family in
  its own right (a damage-divided-among-targets variant is the single
  biggest cluster: "`~` deals N damage divided as you choose among any
  number of target creatures"), not a one-line parser widening. Found while
  scoping MEC-4 (Strive): every one of Strive's 20 real cards pairs "Strive —
  this spell costs `<cost>` more to cast for each target beyond the first."
  (now modeled, `AbilitySpec.strive_cost`) with an "any number of target
  creatures" effect body, so Strive itself shipped with **0** cards reaching
  full `MODELED` — this ticket is the actual remaining blocker on all of them.
- **PAR-12 · The indefinite long tail.** Strategy, current coverage, and a
  worked example: [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Not a ticket
  that can be "closed" — a standing program.
- **PAR-13 · Dungeon room, plane and scheme effect bodies.** The bounded,
  enumerable corner of the tail, called out separately only because a
  *shipped* subsystem is waiting on it: the RULE 309 dungeon engine and all
  four room graphs are built, but a room whose printed effect the grammar
  doesn't model resolves with no effect (fail-closed, `game/dungeons.py`'s
  `room_effect_specs`) — 20 of 30 rooms bind today, the rest are ordinary
  effect-body grammar ("each player loses 2 life unless they discard a
  card", "exile the top two cards of your library. You may play them").
  Planechase (901) and Archenemy (904) are the same one level up: their
  *trigger conditions* are recognized ("whenever chaos ensues", "when you
  set this scheme in motion", "when you planeswalk to ~"), but the bodies
  are exotic even by tail standards ("creatures can't attack you until a
  player planeswalks", "time travel"), so almost every real plane/scheme
  still fails the coverage gate as a whole. Nothing dungeon- or
  variant-specific is missing in either case — this is [PAR-12] work with a
  known card list. (Reaching a Planechase/Archenemy table at all is a
  separate, non-parser gap: [PLR-13].)

## MEC — Game mechanics

> **Permanent non-goals** (never to be built, not gaps): Stickers (RULE 123)
> — `gate.parse_oracle` classifies these `NEVER_SUPPORTED`, a verdict kept
> out of both the coverage count and the backlog ranking — and Attractions
> (RULE 717).

- **MEC-13 · Mana-Potenzial auto-tap has two narrow, documented gaps.**
  (1) `GameEngine.auto_tap_for`/the automatic pre-cast hook
  (`game/engine/casting_mixin.py`'s `_auto_tap_for_cast_if_needed`) only
  ever targets the base/unkicked, X=0 effective cost — an X-spell or
  Kicker spell's *true* cost depends on a choice the player hasn't made
  yet at auto-tap time, so those still need a manual tap or a follow-on
  auto-tap once X/Kicker is chosen. (2) `legal_actions()`'s face-down
  (morph/manifest) cast offer stays real-pool-only —
  `_castable_now_or_via_potential` isn't applied there since RULE 702.37a's
  flat {3} cost isn't expressed through `effective_cast_cost`'s ordinary
  `face` handling. Neither blocks the headline feature (`game/mana_
  potential.py`, `docs/implementation-state/Done_Backend.md` "Mana-
  Potenzial (offen/genutzt) + Auto-Tap"); both are narrow, real cards.
  (3)Multicolor lands and artifacts are counted multiple times, even as
  they can only produce one mana. This makes auto-tapping potentially buggy.

## PLR — Player management

- **PLR-3 · A face-down card in exile isn't redacted.**
  `_redact_hidden_zones` works zone by zone; `GameObject.face_down_in_exile`
  needs per-card characteristic redaction. No multiplayer card makes one
  today.
- **PLR-4 · Names are the identity, unauthenticated.** Two people picking
  the same name share a seat; the second to connect takes over. Fine for a
  LAN table, not for anything public — needs [PLR-9].
- **PLR-5 · The idle watchdog measures silence from the last *action*.** A
  player thinking longer than `MTG_MULTIPLAYER_IDLE_TIMEOUT` is disconnected
  and immediately reconnects (reclaiming by name). Self-healing, but a
  `ping` counted as liveness would remove the flicker.
- **PLR-6 · Mid-interaction state is lost on reconnect.** A targeting modal
  or half-assembled block is rebuilt from the pushed view, which carries
  only committed state. (Backend + frontend halves of one gap.)
- **PLR-7 · A bot that weighs lines.** `GreedyBot`'s `rank_targets`/`play`
  are the intended override points — the base class was split for exactly
  this — but nothing subclasses them; bots take the first legal offer.
- **PLR-8 · Bots at tables of 3+.** Now reachable, since the lobby opens
  tables of up to four: `Bot.rank_targets` takes options as offered and
  `GreedyBot._attack` swings at the first *player* defender in the list, so
  a bot in a pod hits whoever happens to be listed first every turn rather
  than choosing an opponent. Legal, and a bot pod plays out — it just isn't
  a decision. Shares its fix with [PLR-7]: `rank_targets` is the override
  point in both cases.
- **PLR-9 · User accounts.** Login/signup (docs/04 PART 4), auth token
  storage + attachment to API/WebSocket calls, browser-refresh reconnect
  flow (docs/04 S1), and login/signup pages. Saved decks are unscoped until
  this exists — anyone hitting the API sees every deck.
- **PLR-10 · Game history / session persistence.**
- **PLR-11 · Leyline's opening-hand permission.** "As long as this card is
  in your opening hand, you may begin the game with it on the battlefield" —
  a pregame setup permission, not a static or a resolve-time effect, so it
  doesn't fit the `EffectRegistry`/binder pipeline at all. Needs a new
  "opening hand → battlefield" step in `game_session.py`'s
  `_mulligan`/`keep_hand`.
- **PLR-12 · A bot opponent in Goldfisch mode.** There will be no bot implementation. The goldfish mode still counts additional cards being drawn by the goldfish or discarded cards by the goldfish as a stat.
- **PLR-13 · No format switch at the table.** `GameEngine.new_game` takes a
  `game_format=` (`models/game_format.py`, `game/variants.py`), but nothing
  in `api/` or `services/` ever passes one — so Planechase, Archenemy and
  Vanguard are engine-complete and *unreachable from the UI*, playable only
  from Python. Needs a format picker in the Multiplayer **Setup** lobby
  (`LobbyGame`, alongside the mulligan style — plus per-seat avatar choice
  for Vanguard and who's the archenemy for 904) threaded through
  `api/multiplayer.py`'s session build, and the same switch on the goldfish
  side. Frontend halves: the board's Planechase strip and the variant
  badges already exist and render off the session view. Card *text* for
  those formats is a separate, parser-side gap: [PAR-13].
- **PLR-14 · Team variants (RULE 809/810/811).** Two-Headed Giant, Emperor
  and Grand Melee are the part of CR 8 that `models/game_format.py`
  deliberately doesn't model: unlike the RULE 9 variants (which add a card
  pool beside the game) these change the **turn structure itself** — a
  shared life total, two players taking one turn together, a "defending
  team" in combat, RULE 810.8's shared damage assignment. That's a turn-loop
  and combat project, not a format record. The seats it needs exist now (a
  table opens for up to four), so what's left is genuinely the turn loop;
  [PLR-13] to be selectable once built.

## VIS — Visuals

- **VIS-1 · Error/loading states** for network calls (spinner, retry,
  offline message). docs/04 C4.
- **VIS-2 · Saved decks: no rename/duplicate-as-new.** Only save
  (create/update via the tracked id) and delete.
- **VIS-4 · Chat / emotes at the table.**
- **VIS-5 · A move/priority feed.** The board has `move_log`, but in a
  shared game it's hard to see what the opponent just did before your
  response window — a short "Bob hat X gespielt" feed would make the
  3-second auto-pass window usable instead of startling.
- **VIS-6 · Preload the opponent's card art.** Only your own deck is
  preloaded, so an opponent's first play of a card pops in.
- **VIS-7 · Visualize bot actions in real time, with a speed control.** A
  bot's whole turn arrives as one pushed view (the server runs it before
  broadcasting), so there is nothing to watch. Needs the server to push
  between plies, or the client to replay the move log at a chosen speed.
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

- **DB-1 · Stale cached rows keep lossy mana-cost data.** A pre-
  `mana_cost_string` row is priced from the legacy pip tally +
  `converted_mana_cost` via `ManaCost.from_card` — correct total/colors, but
  hybrid/Phyrexian nuance is unavailable until the self-healing refetch
  (`Card.has_mana_cost_data`) happens to hit it. `models/mana_cost.py`,
  `services/lazy_card_loader.py`.
- **DB-2 · The commander ban list is hand-maintained.** Scryfall's
  per-printing `legalities` isn't fetched, so there's no live source.
  Deliberately conservative (only long-standing entries that survived unban
  waves); needs manual updates against the official page.
  `services/commander_legality.py`'s `BANNED_COMMANDER_CARDS`.
- **DB-3 · Commander legality gaps.** No Background / "Friends forever"
  pairing, and no check that a commander is actually legendary.
  `check_commander_legality` covers color identity, the ban list, and plain
  Partner/"Partner with X" only.

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
- **ANA-4 · Dynamic Analysis** plays a predefined number of goldfish matches
  in the background (using only the backend), and records the stats along the
  way. How many lands have actually been drawn in which step, how much mana potential + acutal mana consumption
  has there been in which turn, how much card advantage has there been, how many tutors could be played, which was the turn the commander was on the board etc. this will need to be scaled. Apart from the number of virtual matches and turns per match the bot to use there needs to be selectable for the player.
  The outcome of these analysis criteria will need to be provided as mean value with a standard deviations. The mana production/potential over turns shall be compared with the static analysis in a shared graph.
