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

- **MEC-12 · Make the seven "cEDH"-named saved decks/cubes fully
  playable.** User request 2026-08-06: `Ojer cEDH`, `cEDH Rocco`, `[cEDH]
  Glarb Bloomsday`, `cEDH staples`, `cEDH staples 2`, `cEDH M-K`, `cEDH
  Kinnan` (700+ unique cards across the seven, heavy overlap). Ordinary
  open work, not "no-deferral" scope forced to one sitting. `cEDH Kinnan`
  (100/100) and `cEDH M-K` (97/97) are fully playable — see
  `Done_Backend.md`'s "MEC-12: Kinnan and M-K completed". Coverage as of
  2026-08-19 (re-measure before trusting — these are live, user-editable
  decks):

  | Deck | Coverage | Residual, tracked as |
  | --- | --- | --- |
  | `Ojer cEDH` | 75/77 | Chandra's Incinerator's dynamic cost reduction + a "creature/planeswalker *that damaged player* controls" target kind (doesn't exist); Return the Favor — [MEC-31]. |
  | `cEDH Rocco` | 79/98 | [MEC-31], [MEC-40]. |
  | `[cEDH] Glarb Bloomsday` | 88/100 | [MEC-37], [MEC-38], [MEC-39], [MEC-41]. |
  | `cEDH staples` | 194/215 | [MEC-42]. |
  | `cEDH staples 2` | 483/607 | [MEC-31]–[MEC-39], [MEC-43]. |

  Six names in the raw scan (Balamb Garden, Dol Amroth, Jodah the unifier,
  Seymour Guado, Thrum of the Vestige, Zidane Tribal) aren't real Scryfall
  cards — not a gap, don't chase them. Worklog detail for what's shipped —
  batch by batch, why each piece is built the way it is — is in
  `Done_Backend.md`'s "seven 'cEDH'-named saved decks" entries, not here.

- **MEC-31 · RULE 702.172 Spree (+ RULE 702.53 Escalate).** Unbuilt modal
  casting mechanic — "choose one or more additional modes, paying each
  mode's own extra cost" (Spree) / "…for {N} more each" (Escalate) —
  neither keyword line does anything today. Blocks `Ojer cEDH`'s Return
  the Favor and part of `cEDH Rocco`'s pool. Building Spree likely unlocks
  Escalate for free (same "choose N, pay per choice" shape).

- **MEC-32 · `RulesEngine.draw()`'s per-card event granularity.**
  `draw(player, count)` calls `_single_draw` once per card, each firing its
  own independent `EventType.DRAW` with a hardcoded `count=1` — so no
  replacement can see "this player is attempting to draw 2+ cards as one
  instruction" (Alms Collector's "if an opponent would draw two or more
  cards") or "this is the first draw in the current draw step" (Notion
  Thief/Chains of Mephistopheles's "except the first one they draw in each
  of their draw steps" — needs a draw-*step*-scoped counter, distinct from
  the whole-turn `GameState.cards_drawn_this_turn`). Fix: restructure
  `draw()` to fire one event for the whole instruction *before* splitting
  it into individual card moves (mirroring how a replacement can already
  *grow* one event's `count` and have that honoured). Touches the single
  most heavily-exercised primitive in the engine — needs its own careful
  pass with full regression coverage, not a fix buried in an unrelated
  batch. Closes Alms Collector, Notion Thief, Chains of Mephistopheles
  (`cEDH staples 2`).

- **MEC-33 · Omen Machine.** "Players can't draw cards. At the beginning of
  each player's draw step, that player exiles the top card of their
  library... casts it without paying its mana cost if able." A flat draw
  prohibition (an easy sibling of the already-shipped
  `GrantSearchProhibitedEffect`) paired with a genuine draw-step
  *replacement mechanic* (exile-and-free-cast instead of drawing, for
  *every* player, every turn) that doesn't exist yet.

- **MEC-34 · Animate Dead / Necromancy reanimator Auras (RULE 303.4f).**
  Real reanimator Auras, not plain graveyard recursion (Reanimate's own
  shape) — both print "Enchant creature card in a graveyard", RULE 303.4f's
  special case where the Aura's own target isn't a permanent, so it can't
  attach as it resolves the ordinary way. Blocker: `RulesEngine.
  _resolve_permanent_spell` (`game/rules/casting_mixin.py` ~line 1140) —
  for any "enchant"-kind Aura it always does `if not (targets and self.
  attach_to_target(obj, targets[0])): self._move_to_graveyard(obj)` right
  after `add_to_battlefield`; since the target is a graveyard `GameObject`,
  `attach_to_target` fails and the Aura is sent to its own graveyard before
  its own queued "when this enters" trigger ever resolves. Fix, 4 parts:
  (1) a new branch recognizing "target is a graveyard-zone card" and
  skipping the auto-graveyard-on-failed-attach for that case (the Aura
  stays on the battlefield unattached until its own ETB fixes that); (2)
  the ETB effect itself — return the target creature card to the
  battlefield under the caster's control (`ReturnFromGraveyardEffect(
  under_your_control=True)`), then attach this Aura (self) to the object
  reanimation just created — needs `AttachEffect` to gain a third referent
  mode reading `context.created_objects`/`previous_targets` (the same way
  `ReturnAllExiledWithEffect`'s siblings already do), since neither a RULE
  115 target nor a plain referent fits "the card my own previous clause in
  this resolution just returned"; (3) a "when this Aura leaves the
  battlefield, that creature's controller sacrifices it" trigger —
  `GameObject.attached_to` is never cleared by `GameState.
  remove_from_battlefield`, so a plain `{"event": "LEAVES_BATTLEFIELD",
  "condition": {"subject": "self"}}` trigger reading `self.source.
  attached_to` at resolve time already has a stable value; (4) confirm
  RULE 704.5n's "Aura attached to nothing → owner's graveyard" SBA sweep
  doesn't fire in the window between the Aura entering and its own ETB
  resolving (may already be safe — verify, exempt if not). The
  self-referential "it loses 'enchant creature card in a graveyard' and
  gains 'enchant creature put onto the battlefield with this Aura'"
  text-change clause is RULE 303.4f reminder text with no separate
  gameplay effect once (1)-(4) are right — drop as a documented
  simplification. Genuinely a multi-part build, not a single primitive
  gap. Closes Animate Dead, Necromancy (`cEDH staples 2`).

- **MEC-35 · Leonin Arbiter.** "Players can't search libraries. Any player
  may pay {2} for that player to ignore this effect until end of turn."
  Two parts: widen `GrantSearchProhibitedEffect` to apply to *every*
  player including its own controller (today hard-coded "opponents only"
  for Stranglehold); and a genuinely new "any player may pay a cost, any
  time, for a personal exemption until end of turn" special action — not a
  one-shot aggregate-outcome tax like Rhystic Circle's `request_all_
  players_decline_or` (MEC-30), since this is repeatable per player and
  grants a standing exemption rather than cancelling one pending effect.

- **MEC-36 · Damping Sphere.** "If a land is tapped for 2 or more mana, it
  produces {C} instead of any other type and amount. Each spell a player
  casts costs {1} more to cast for each other spell that player has cast
  this turn." Two unbuilt pieces: a mana-type-override-by-amount-produced
  static, and a genuine per-caster storm-count-scaled tax (`cost_
  reduction`'s existing `per` vocabulary scales by a board *count*, not by
  how many spells the taxed player has personally cast this turn — needs a
  new per-player `GameState.spells_cast_this_turn` counter).

- **MEC-37 · Doomsday's "exile up to five cards in a pile."** A genuinely
  separate unbuilt mechanic, not a plain search — `SearchLibraryEffect`'s
  existing `zones` param doesn't cover ordering five found cards into one
  pile the caster then draws through card by card.

- **MEC-38 · Necropotence's three-clause engine.** A standing draw-step
  skip needs a battlefield-lifecycle hook into `Player.player_effects`
  that doesn't exist yet, plus a delayed face-down-exile-to-hand shape
  (pay life, exile top card of library face down, put it into hand at the
  next turn's beginning).

- **MEC-39 · Opposition Agent's control-during-search.** "You control your
  opponents while they're searching their libraries." A real, unbuilt
  control-exchange-during-a-choice shape — distinct from the existing
  one-shot Gilded Drake-style control exchange (RULE 701.10), since this
  one is conditional and scoped to the duration of a specific choice.

- **MEC-40 · `cEDH Rocco`'s remaining gaps** (Spree/Escalate split out as
  [MEC-31]). 19 gaps spanning several distinct unbuilt shapes, not yet
  individually diagnosed beyond: a "power greater than its base power"
  per-creature qualifier on the `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`
  aggregate; a card's own self-referential "cast this from your graveyard
  **or exile**" permission, distinct from the existing granted-by-another-
  permanent shape; "Saddle"/RULE 702.172-adjacent Vehicle crewing add-ons;
  a cost-payment restriction ("can't pay life or sacrifice permanents to
  cast/activate"); a same-name ETB-draw-engine qualifier; others not yet
  individually diagnosed. Re-measure and diagnose fresh rather than
  assuming this list is complete or unchanged.

- **MEC-41 · `[cEDH] Glarb Bloomsday`'s remaining gaps** (Doomsday,
  Necropotence, Opposition Agent split out as [MEC-37]/[MEC-38]/[MEC-39]).
  12 gaps: Ad Nauseam/Gifts Ungiven/Bring to Light's own reveal/choice
  shapes; Counterbalance's live-comparison counter-spell condition; Valley
  Floodcaller's own trigger (a named-subtype-list creature group —
  `PumpEffect` has no `subtypes` list param the way `AddCountersEffect`
  does); Nissa/Sylvan Library's own multi-step choices — each needs
  individual diagnosis, not a guess.

- **MEC-42 · `cEDH staples`'s remaining 21 gaps.** Abrupt Decay, Ashling
  the Limitless, Cabal Ritual, Culling Ritual, Dauthi Voidwalker, Delay,
  Derevi Empyrial Tactician, Mana Crypt, March of Swirling Mist, Orcish
  Bowmasters, Praetor's Grasp, Sevinne's Reclamation, Teferi Time Raveler,
  Tinder Wall, Touch the Spirit Realm, Tymna the Weaver — plus Ad Nauseam/
  Necropotence/Opposition Agent/Ranger-Captain of Eos/Sylvan Library
  shared with `[cEDH] Glarb Bloomsday` (see [MEC-38], [MEC-39], [MEC-41]).
  None individually diagnosed yet.

- **MEC-43 · `cEDH staples 2`'s undiagnosed remainder.** Once [MEC-31]
  through [MEC-39] are subtracted, dozens of distinct shapes remain, none
  individually diagnosed. Re-measure and diagnose per card rather than
  batch-guessing.

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
