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

(none open)

## PAR — Parser

- **PAR-12 · The indefinite long tail.** Strategy, current coverage, and
  worked examples: [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) — split into
  two tracks there, **basic mechanics** (generic shapes, worked by raw
  cache-wide yield) and **set-specific mechanics** (one expansion/precon's
  own signature keyword, worked deck-first against a saved deck's actual
  commander/product). Not a ticket that can be "closed" — a standing
  program. Planechase (901)/Archenemy (904) plane/scheme card *bodies* live
  here too (13/309 measured 2026-08-04) — their trigger conditions are
  recognized, but the bodies are exotic even by tail standards, so this is
  ordinary long-tail work with a known card list, not a distinct gap.
  (Reaching a Planechase/Archenemy/Vanguard table at all is wired up end to
  end — Setup's format picker, `services/lobby.py`, `api/multiplayer.py`/
  `api/game.py` — see Done_Backend.md "PLR-13". Vanguard's own remaining
  piece — a per-seat avatar picker, and its avatars' card text — is a
  permanent non-goal, not a queued gap; see the MEC callout below.)

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

- **MEC-43 · Make every "cEDH"-named saved deck/cube fully playable**
  (sole tracker for this work). User request 2026-08-06, originally seven
  decks; an eighth (`K'rrik cEDH`) has since been created by the user and
  is folded into the same ticket rather than filed separately — this is a
  *collection* of live, user-editable decks, not a fixed card list, so
  expect it to keep growing. Ordinary open work, not "no-deferral" scope
  forced to one sitting. Coverage re-measured 2026-08-24 (own script, not
  yet a checked-in tool — see the MEC-44 proposal below; re-measure again
  before trusting, per the ticket's own recurring caveat):

  | Deck | Coverage | Residual, tracked as |
  | --- | --- | --- |
  | `Ojer cEDH` | 77/77 parser-coverage | Balin's Tomb (the LOTR alt name for Ancient Tomb) still doesn't *resolve as that name* — see CLAUDE.md's `flavor_name` gotcha, an import/card-database display gap, not a coverage one. |
  | `cEDH Rocco` | 98/98 | fully playable. |
  | `[cEDH] Glarb Bloomsday` | 100/100 | fully playable. |
  | `cEDH staples` | 215/215 | fully playable. |
  | `cEDH M-K` | 97/97 | fully playable (MEC-12's Kinnan/M-K completion batch still holds). |
  | `cEDH Kinnan` | 100/100 | fully playable (ditto). |
  | `cEDH staples 2` | 572/606 (1 name not a real card) | 34 genuinely uncovered — see below. |
  | `K'rrik cEDH` | 50/71 | 21 uncovered — see below. |

  Re-measured 2026-08-24 with `scripts/deck_coverage.py` (the MEC-44 tool
  below, now checked in and used for every number on this page). Of the
  six names an earlier ad hoc diagnosis called "aren't real Scryfall
  cards," four (Balamb Garden, Jodah, the unifier, Seymour Guado, Zidane
  Tribal — all Final Fantasy Universes Beyond cards) now resolve as real,
  cached, genuinely-uncovered cards; only `Thrum of the Vestige` still
  doesn't resolve at all (and Dol Amroth no longer appears in the
  decklist text). Don't trust that "not real" framing without
  re-checking — a card-pool refresh can un-stale it, same as a coverage
  number can. Worklog detail for what's shipped — batch by batch, why
  each piece is built the way it is — is in `Done_Backend.md`'s "seven
  'cEDH'-named saved decks" entries (name kept for continuity), not here.

  **MEC-44, shipped**: `scripts/deck_coverage.py` — parses a saved deck's
  `mainboard_text`/`commander_text` the same way `parser/deckliste_
  parser.py` already does, then runs each unique card through
  `is_registered`/`parse_oracle` exactly like `coverage_report.py` does
  cache-wide, keyed off the resolved `Card.name`'s canonical
  `"Front // Back"` form (not the decklist's own front-face-only text —
  the real bug an earlier one-off version of this script had, and the
  reason every number on this page needed re-verifying once the tool
  existed to check them properly). `python scripts/deck_coverage.py
  ["Deck Name" ...] [--uncovered]`.

  **Near-free reuses — closed 2026-08-21** (all 22 named cards;
  `Done_Backend.md`'s "MEC-43" entry has the full primitive-by-primitive
  detail): Aetherflux Reservoir, Altar of Dementia (new `GameObject.
  sacrificed_cost_power` + `MillEffect.count_selector`), Burnt Offering/
  Sacrifice/Rain of Filth, Conspicuous Snoop (`grant_borrowed_activated_
  ability`'s new `source_mode="top_of_library"`), Defense of the Heart,
  Earthcraft (`tap_others`' existing bare-type match), Hermit Druid
  (`dig_until`'s new `rest_destination="graveyard"`), Jeweled Amulet (new
  `ManaPool.last_payment_types` + `ActivationCost.note_spent_color` +
  `AddManaEffect.color_from_source_noted_color` — closed in a follow-up
  pass rather than left a third-deferral risk), Kogla the Titan Ape (a new
  `defending_player_id` field on the `ATTACKS` event), Leyline of the
  Void/Rest in Peace (the new `graveyard_redirect` static, `scope=
  "opponent"`/`"any"`), Soulless Jailer (`graveyard_library_entry_
  prohibition`'s new `card_type="permanent"` + `cast_prohibition`'s new
  `zones` allowlist), Chain of Smog (new `CopySelfControlledByPrevious
  TargetEffect`), Destiny Spinner (`GrantCantBeCounteredEffect`'s new
  two-type `scope` — its land-animation half is the recurring "animate a
  noncreature permanent" gap below, deliberately left unbound), Llawan
  Cephalid Empress (`ReturnToHandEffect`'s new `"opponents_creatures"`
  selector + `cast_prohibition`'s new `color`/`creature_only`), Mana
  Breach (new `BounceOwnLandFromTriggerEffect`), Selvala Heart of the
  Wilds (new `DrawIfTriggerObjectGreatestPowerEffect`), Shifting Woodland
  (`BecomeCopyUntilEndOfTurnEffect` retargeted at the new
  `"graveyard_permanent"` target kind), Tataru Taru (`not_controllers_
  turn` trigger predicate + `once_per_turn`), Uba Mask (new
  `draw_exile_face_up` replacement), Acererak the Archlich
  (`EachPlayerPayOrEffect`'s new `scope="each_opponent"`/`effect_targets=
  "controller"` + a new `not_completed_dungeon` trigger predicate).
  Covered by `tests/test_mec43_near_free_reuses.py` (16 tests).

  **Round 2 near-free reuses — closed 2026-08-24** (17 more cards; 5 via
  parser-regex widenings, 12 hand-authored; `Done_Backend.md`'s "MEC-43"
  entry has the full primitive-by-primitive detail): Kunoros, Hound of
  Athreos (`graveyard_library_cast_prohibition`/`_entry_prohibition`'s new
  `zones` param, closing it via the parser); Hushbringer
  (`trigger_prohibition`'s DIES sibling, parser); Thalia, Heretic Cathar
  (`enters_tapped_static`'s per-word `nonbasic`, parser); Thoughtseize/
  Inquisition of Kozilek (`reveal_hand_choose_discard`'s new
  `max_mana_value`/trailing `lose_life` rider, parser); Beacon of Unrest
  (`targeting`'s new `graveyard_artifact_or_creature` filter +
  `shuffle_self_into_library`); Rise from the Grave/Chainer, Dementia
  Master (`GrantUntilEffect`'s `duration="rest_of_game"`/`previous_
  subject` combo applied to `type_change`/`color_change`, reading back a
  reanimated creature the same way "It fights…" reads a prior target);
  Tenacious Dead (`ReturnFromGraveyardEffect`'s new `tapped`/
  `trigger_subject_key="remembered"`, via `PayCostThenEffect.remember_
  trigger_subject`); Sanctifier en-Vec (`ExileAllGraveyardsEffect`'s new
  `colors` filter + `graveyard_redirect`'s new `colors` param); Kenrith's
  Transformation (the "Elk" template — `remove_all_abilities`/
  `type_change`/`color_change` composed on `affects="attached_
  permanent"`); Conqueror's Flail/Faeburrow Elder (`count_selector`'s new
  `"colors_among_permanents_you_control"`, plus `static_conditions`' new
  `"all"` AND-combinator for Conqueror's Flail's two-gate cast lockdown);
  Delney, Streetwise Lookout (the qualified `combat_restriction` +
  `TriggerDoublerEffect`'s new `min_power`/`max_power` axis); Runic
  Armasaur (`effect_binder._group_ok`'s list-`type` OR support, hand-
  authored directly onto `EventType.ACTIVATED_ABILITY` rather than taught
  to the parser's trigger-verb grammar); Peer into the Abyss
  (`DrawCardEffect`'s new `"half_target_library_round_up"` selector +
  `LoseLifeEffect`'s new `amount_from_half_target_life`/`previous_
  subject`); Soul Conduit (the new `ExchangeLifeTotalsEffect`). Covered by
  `tests/test_mec43_round2_near_free_reuses.py` (21 tests). Ojer Axonil,
  Deepest Might turned out to already be covered (MEC-30, before this
  round's diagnosis) — an earlier diagnosis pass's own coverage-tool bug,
  not a real gap; no work needed.

  **Round 2 remainder, not yet built** (`cEDH staples 2`'s 34 + `K'rrik
  cEDH`'s 21 uncovered, re-measured after the closures above — see the
  coverage table; the clustering below is unchanged from the original
  2026-08-24 diagnosis and still **not cross-checked against `primitives`/
  `Done_Backend.md` the way an actual batch must be** for anything past
  what closed above — treat every "near-free" call as a hypothesis to
  verify, not a confirmed primitive match):

  *Near-free reuse candidates, clustered* (a shape already shipped is
  cited by name; confirm with `python $BENCH primitives '<shape>'` before
  building):
  - **`SearchLibraryEffect` criteria/gate widenings** (already-general):
    Beseech the Queen (mana value ≤ lands you control), Final Parting
    (one search, two destinations — hand and graveyard), Search for
    Glory (a three-type OR criteria + life gained per {S} spent), Myriad
    Landscape (paired search, "share a land type").
  - **The "loses all abilities, becomes a 3/3 green Elk creature" template**
    — Kenrith's Transformation closed above; Oko, Thief of Crowns' +1
    shares the same clause but needs `grant_until` resolve-time wiring
    plus Oko's other two loyalty abilities (its own −5 is a control
    exchange, RULE 701.10, the same shape already shipped for Gilded
    Drake/Volatile Stormdrake below) — a bigger lift than "near-free",
    left open as its own small batch rather than folded into round 2.
  - **Small, self-contained**: Vilis, Broker of Blood ("whenever you lose
    life, draw that many cards" — check whether a LOSE_LIFE event already
    carries an amount a trigger can read, the same shape Aetherflux
    Reservoir's `spells_cast_this_turn` count-selector reuse established
    for a different event); Volatile Stormdrake (the Gilded Drake-shaped
    control exchange, RULE 701.10, already shipped, plus an
    Energy-conditional sacrifice-unless-pay).

  Dance of the Dead is the odd one out in the reanimation family (closed
  above) — RULE 704.5n Necromancy-shaped, the Aura itself ends up
  attached to what it just reanimated, a genuinely different shape from a
  plain spell reanimation; still open, not near-free.

  **A recurring primitive gap, not yet built**: "animate a noncreature
  permanent into an X/Y creature with keywords" has no existing shape in
  this engine (Destiny Spinner's land-animation half is the only instance
  in the currently-tracked residual, but the template recurs across the
  wider cache — worth building as a real primitive rather than
  re-deferring per card that needs it; the "Elk" template above is
  related but distinct — no vehicle/artifact-only scoping — and
  shouldn't be conflated with this one just because both say "becomes a
  creature").

  **Genuinely bigger builds, each its own real subsystem** (the original
  six, plus four more this round's diagnosis surfaced): Aluren (a
  standing, *any-player*-scoped, class-wide free-cast permission —
  distinct from every existing single-card-armed free-cast grant, and the
  first grant not scoped to one controller), Knowledge Pool (a cast-
  *substitution* mechanism — intercepts the act of casting into a shared,
  growing exiled pool, not a resolve-time effect), The Tabernacle at
  Pendrell Vale (a mass, continuously-re-derived, layer-6-granted
  sacrifice-unless-pay applied to *every* creature on the board, including
  opponents'), Smokestack (N-per-player simultaneous interactive sacrifice
  choices every upkeep, scaled by a counter — bigger than the existing
  one-pick-per-player sequencing), Rings of Brighthearth ("copy an
  activated ability, choose new targets" — `StackItem.stack_id` from
  ENG-26 gives it something to reference, but the copy-and-re-resolve
  mechanism itself doesn't exist), Isochron Scepter (a repeatable "cast a
  copy of an exiled card, leaving the original behind" activated ability —
  close to but distinct from cascade's free-cast-from-exile); K'rrik, Son
  of Yawgmoth ("for each {B} in a cost, you may pay 2 life rather than pay
  that mana" — a standing, unscoped alternative-payment permission over
  *any* cost, broader than every existing wildcard-color mechanism, which
  all substitute *color*, never *whether mana is needed at all*); Maralen
  of the Mornsong (a genuine mass draw-*replacement*, RULE 121-adjacent —
  "players can't draw cards" plus a per-player substitute at the moment
  each would draw, distinct from every existing single-recipient draw
  replacement); Keen Duelist (a simultaneous mutual reveal-and-compare —
  no existing two-player-at-once comparison shape); Scroll Rack (exile a
  chosen subset of hand cards face down, draw that many from the library,
  then *reorder the exiled cards back on top* — the reordering step has no
  existing analogue).

  **Narrower, real gaps:** Runic Armasaur closed above.
  Umezawa's Jitte's modal "choose 1" removal ability (check whether an
  *activated* ability can already carry `modes`/`modes_choose` the way a
  triggered ability's own RULE 700.2 modes do — if not, that's the actual
  gap, not the card); Swift Reconfiguration (a type-overwrite-to-Vehicle
  combined with a granted Crew N — check `grant_mana_ability`'s own
  cost-upgrade idiom for a reusable shape before assuming this needs
  something new);
  Doomsday Excruciator/Demonic Bargain (both exile-most-of-the-library-
  face-down-then-search — check MEC-37's Doomsday machinery for reuse
  before assuming new); Mesmeric Orb ("whenever a permanent becomes
  untapped" — CLAUDE.md's own trigger-verb table deliberately excludes
  "becomes untapped" today since no event carries an `instance_id` for
  it; a real, narrow, project-level gap rather than a build-it-now item).

  **Not yet clustered** (the remainder of `scripts/deck_coverage.py
  --uncovered`'s output for both decks after the closures above — Bontu's
  Monument, Commander's Plate, Crypt Ghast, Dark Petition, Drain Life,
  Final Punishment, Homeward Path, Jin-Gitaxias, Kodama of the East Tree,
  Korvold, Kozilek, Butcher of Truth, Ledger Shredder, Mizzix's Mastery,
  Poison the Cup, Sheoldred, Whispering One, Spoils of Blood, Syphon Mind,
  Talion, the Kindly Lord, Tergrid, God of Fright — plus a second group
  the original 2026-08-24 diagnosis missed entirely: Angel's Grace,
  Archon of Valor's Reach, Command Beacon, Containment Priest, Grim
  Hireling, Heliod, Sun-Crowned, Hoarding Broodlord, Ikra Shidiqi, the
  Usurper, Legolas's Quick Reflexes, Sword of Feast and Famine,
  Worldgorger Dragon — a reminder that even a careful hand-rolled triage
  can undercount, and part of why `scripts/deck_coverage.py --uncovered`
  is now the source of truth for "what's left" rather than any list
  frozen into this file): a first skim suggests most are further
  near-free reuses of already-shipped shapes (mass edicts, triggered mana
  abilities, count-selector token sizing, ordinary ETB/attack trigger
  composition) rather than new subsystems, but none of that is verified
  yet — don't start a batch here without first running each through
  `parser_probe.py`/`python $BENCH primitives` the way every prior batch
  in this ticket did.

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

- **VIS-1 · Error/loading states** for network calls (spinner, retry,
  offline message). docs/04 C4.
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
