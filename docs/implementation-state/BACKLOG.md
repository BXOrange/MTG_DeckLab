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

- **ENG-1 · Re-validate existing attachments every SBA pass.** RULE
  704.5m/n also cover a host that stays on the battlefield but becomes
  newly illegal (enchanted creature gains protection after the Aura
  attached); only "host left the battlefield" is checked.
  `RulesEngine._detach_attachments_from`. **Blocks [PAR-6].**
- **ENG-2 · `SacrificeEffect` auto-picks the victim.** Annihilator's
  "defending player sacrifices N permanents" (RULE 702.86) is still a
  non-interactive MVP choice. Upgrade via the existing
  `RulesEngine.request_choose_objects(..., action="sacrifice", ...)` (as
  Tevesh Szat/Professor Onyx already do) — *not* `_sacrifice_candidate`.
  `game/effects.py`.
- **ENG-3 · Two cost-payment auto-picks left behind.** A spell's own "as an
  additional cost, sacrifice a creature" (RULE 601.2b,
  `_pay_additional_cast_cost`) still auto-picks, and any cost-payment
  discard (`ActivationCost.discard`) still uses non-interactive
  `RulesEngine.discard`. Cost payment is one synchronous call, so this needs
  the `tap_choices`/`sacrifice_choice` "choice as an action parameter" shape
  threaded into `cast_spell` — **not** a `request_choose_objects`
  `pending_choice`, which only works mid-resolution. `game/game_engine.py`.
- **ENG-4 · Manual trigger-ordering + a targeted/optional trigger.** A
  trigger placed via the opt-in RULE 603.3b ordering choice is placed
  directly and never pauses for its own target/"you may" choice. Both work
  alone; only the combination is unhandled. `RulesEngine._place_triggers`.
- **ENG-5 · Multi-target groups aren't auto-derived for casting.**
  `StackItem.target_groups` works, and a *triggered* ability gathers one
  group per effect automatically, but a spell/activated-ability caster must
  still supply groups explicitly. Needs `requirements_with_targets`-driven
  cast-offer + frontend flow to build them per requirement, mirroring
  `gameBoardView.js`'s existing "expand into N single-target rounds".
- **ENG-6 · `CopyPermanentEffect` has no copy-of-a-copy.** RULE 707.2
  copiable values interacting with other copy effects isn't modeled; it
  copies from the printed card. `game/effects.py`.
- **ENG-7 · A token copy never offers its own `enter_as_copy` choice.**
  Unlike `_resolve_permanent_spell`, `create_token` skips the RULE
  614.1c/614.12 choice. No card in the pool needs it yet.
  `RulesEngine.create_token`.
- **ENG-8 · Layer 3 (RULE 612) is scoped to one consumer.** Word
  substitution over a derived `effective_oracle_text`, read *only* by
  `combat.protections_of_text` — not a re-parse, so bound abilities and
  keywords are unaffected by a text rewrite. `continuous.py`'s `text`
  sublayer.
- **ENG-9 · RULE 613.8 dependency ordering is bounded to one sublayer.**
  Only layer 2's controller-scoped `affects` is dependency-ordered. Provably
  safe for today's effect vocabulary; extend if a selector ever reads
  another object's derived state. `continuous._order_control_effects`.
- **ENG-10 · Layer 1 "become a copy" mutates in place.** Only the
  *conditional* copy case (Vesuvan Shapeshifter) got true per-recompute
  layer-1 treatment. `game/copy_mechanics.py`, `game/continuous.py`.
- **ENG-11 · A granted trigger isn't identity-scoped without an
  `instance_id`.** Layer-6-granted triggers scope per-grantee off the firing
  event's `instance_id`; an event shape carrying none isn't filtered by
  identity. No card grants a trigger off such an event today.
  `continuous._granted_trigger_condition`.
- **ENG-12 · Two independent targets on one ability.** Brass Squire, Halvar
  God of Battle, Archdruid's Charm's third mode (which also wants a dynamic
  damage amount tied to the other effect's target) are left unregistered
  rather than guessed at. See
  [11_CARD_CATALOGUE_AUTHORING_GUIDE.md](../Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)
  §5.
- **ENG-13 · No per-firing dynamic reference for a *granted* ability.**
  `check_rampage`/`check_ward` build a fresh `TriggeredAbility` per firing,
  and `TriggeredAbility.reflexive` covers a fixed-shape target found by
  `instance_id` — but neither generalizes to an arbitrary grant. Blocks
  Kaldra Compleat's "exile that creature" and Sigarda's Aid's "attach *it*".
- **ENG-14 · Simian Sling's "defending player" is attacker-scoped.**
  Resolved off its own combat-defender stamp, only set when Simian Sling is
  itself the attacker; reconfigured onto another creature the trigger fires
  but finds nobody. `effects._defending_player_of`,
  `ability_catalogue._simian_sling`.
- **ENG-15 · Subset attacker selection.** Attacking swings with **every**
  able creature (one "⚔️ Angreifen (N)" control). Per-creature select needs
  the backend to accumulate declared attackers rather than replace them.
  Paired frontend work: [VIS-3].

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
- **PAR-6 · RULE 702.16e's "This effect doesn't remove this Aura." tail.**
  Leaves six of the eight protection-from-chosen-colour Auras UNMODELED
  even though the grant itself is modeled. **Not safe to claim as a no-op**
  — it only reads as one because RULE 704.5n isn't implemented. Build with
  [ENG-1] or it becomes a silent landmine.
- **PAR-7 · Kicker `{X}`'s own paid-X variant.** Emblazoned Golem, 1 card.
- **PAR-8 · Granting Cycling to other cards.** "Each card in your hand has
  cycling {2}" — a static-grant shape, not keyword recognition.
- **PAR-9 · Generic Cycling execution for unregistered cards.** The
  `discard_self` primitive exists; binding a bare oracle-recognized
  "cycling" spec into a real activatable ability is hand-authored per-card.
- **PAR-10 · Jin-Gitaxias-style compound activation condition.** "…and only
  if you have seven or more cards in hand" stacked on sorcery-speed timing;
  the whole clause fails closed rather than dropping the second condition.
- **PAR-11 · `no_untap_optional` is unreachable by any real card.** RULE
  502.1's engine + `legal_actions` + frontend toggle all ship, but each of
  the ~46 real cards pairs the clause with an unmodeled second one — usually
  "target permanent doesn't untap for as long as *this* remains tapped"
  (~15+ cards), sometimes "gain control of target creature". Fail-closed
  parsing means the static never binds. Modeling the lock-down family would
  unlock the toggle for real play, not just synthetic tests
  (`tests/test_batch8_permission_statics_family.py`).
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

- **MEC-1 · Fight** (~40 cards) — "target creature you control fights target
  creature …". No `FightEffect` at all. Good next-batch candidate.
- **MEC-2 · Monstrosity / Adapt** (~63 cards) — needs a
  `GameObject.is_monstrous`-style flag, a "becomes monstrous/adapted" event,
  and its own effect types. A clean separate mechanic, not an extension of
  the firebreathing-pump family.
- **MEC-3 · Goad (RULE 701.15)** — no primitive, no recognition. "Attacks
  each combat if able" matches the shape `combat.py`'s existing must-attack
  keywords enforce; "and attacks a player other than [goader] if able" needs
  a per-object "may not attack this specific player" restriction that
  doesn't exist. Acquired Mutation is the one blocked real card. Squarely a
  multiplayer mechanic — inert in 1v1, where "a player other than you" has
  only one answer.
- **MEC-4 · Strive** — not a RULE 702 keyword in this catalogue at all; a
  per-extra-target cost escalation needing its own grammar.
- **MEC-5 · Manifest dread** — a new subsystem, distinct from
  Monarch/Initiative/Emblem.
- **MEC-6 · Embercleave's cost reduction** — "costs {1} less for each
  attacking creature you control" needs a board-count-*during-declare-
  attackers* `count_selector` on the existing `self_cost_reduction_for`.
- **MEC-7 · Timely Ward's conditional flash** — needs a
  `"targets_a_commander"` key in `conditional_flash`'s condition whitelist.
  `game/condition_query.py`.
- **MEC-8 · An emblem's own activated ability.** RULE 114.4 permits one;
  `RulesEngine.create_emblem` files only `TriggeredAbility`/`StaticAbility`
  and would silently drop an `ActivatedAbility`. No real emblem prints one.
- **MEC-9 · Designation inheritance.** RULE 725.4/726.4 — the monarch/
  initiative-holder leaving the game should pass it to the active player.
  Prohibition/cost-modification statics also remain unmodeled.

> **Permanent non-goals** (never to be built, not gaps): Stickers (RULE 123)
> — `gate.parse_oracle` classifies these `NEVER_SUPPORTED`, a verdict kept
> out of both the coverage count and the backlog ranking — and Attractions
> (RULE 717).

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
- **VIS-3 · Per-creature attacker selection UI** — the frontend half of
  [ENG-15]; blocked on it.
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
