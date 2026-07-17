# Backend TODO

Open backend items only — **when an item is finished, move its narrative
into the matching section of
[Done_Backend.md](../docs/implementation-state/Done_Backend.md) (section
headers here mirror there) instead of leaving it `[x]` in place.** This file
is read in full fairly often (by humans and Claude); a `[x]` entry with a
full writeup left behind defeats the split and re-bloats every future read.
A one-line "moved to Done_Backend.md, section name" pointer, or just
deleting the line outright, is enough — the ToDo/Done split only pays off if
it's kept up, see CLAUDE.md "Conventions & gotchas".
See [../docs/implementation-state/10_COMPLETION_ROADMAP.md](../docs/implementation-state/10_COMPLETION_ROADMAP.md)
for the dependency-ordered plan to finish the implementation.

## Rules Engine (Phase 2) — remaining

- [ ] Oracle-text → effect *parser* (docs/07 PART 5) — design in
      [../docs/concepts/09_ORACLE_EFFECT_PARSER.md](../docs/concepts/09_ORACLE_EFFECT_PARSER.md)
      (two-stage: front-end parses `oracle_text` → `AbilitySpec` IR;
      binder maps IR → `GameEffect`; fail-closed `MODELED`/`UNMODELED`
      coverage gate). Everything shipped so far is narrated in
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)" — search there for a mechanic's name rather
      than duplicating its writeup here. `parser/oracle/processing_list.py`
      tracks cache-wide coverage; run `coverage_over_cards()` for the
      current number before quoting one (22.8% of 2,909 cards, i.e. 664
      fully `MODELED`, as of 2026-07-16).

      **Still open:**
      - N>=2 multi-target is only wired up for `destroy`/`exile`/`damage`
        (the three effect classes/real cards driving it so far) — other
        targeting families (`return_to_hand`/`tap`/`add_counters`/
        `return_from_graveyard`) stay N=1-only until a real card needs it.
        Also still out of scope: cross-target constraints ("two target
        creatures controlled by *different* players", Run Away Together).
        (2+ *different* targeting effects on one spell/ability sharing a
        target list *is* now fixed — `StackItem.target_groups`,
        `game/rules_engine.py`'s `resolve_top_of_stack`/
        `_continue_trigger_multi_target` — but a spell/activated-ability
        caster still has to supply `target_groups` explicitly; nothing
        auto-derives it from a plain flat `targets` list yet, since no
        real card needs the combination today. A triggered ability's own
        target choice already gathers one per effect automatically. When a
        real card needs this for casting, `game_engine.py`'s
        `requirements_with_targets`-driven cast-offer/frontend flow needs
        extending to build `target_groups` per requirement, mirroring the
        existing per-requirement "expand into N single-target rounds"
        pattern `gameBoardView.js` already uses for one N>=2 effect.)
      - "Remove a counter" cost: only the fixed count shape
        (`costs._REMOVE_COUNTERS_RE`, already existed) is reachable from
        oracle text now — variable-count phrasings ("remove X counters",
        "remove up to 3 counters", "remove any number of counters",
        "remove all counters from all permanents", ~38 real cards found)
        still fail closed.
      - Search/tutor: still unrecognized — "search your library **and/or
        graveyard**" (Doomsday/Finale of Devastation — `request_search`
        only reads `player.library`, a real engine gap, not just
        unparsed); a split destination per found card ("put one onto the
        battlefield tapped and the other into your hand", Cultivate/
        Kodama's Reach — a different effect shape, one search always has
        one destination); "search for N cards and exile the rest"
        (Doomsday).
      - "You may look at the top card of your library any time" (a
        standing permission) — the engine capability exists
        (`game/top_library.py`, Done_Backend.md "Rules Engine
        (Phase 2)") but only via hand-authoring (Oracle of Mul Daya,
        Glarb); the parser's own front-end recognition of the clause is
        a separate follow-up (`coverage_over_cards()` only sees the
        parser, not the hand-authored registry, so the processing-list
        template still shows all 13 cards unclaimed).
      - `prevent_damage`'s two real cards (Riot Control/Thought Lash) — a
        one-shot *spell effect* granting a temporary shield
        (Regenerate-shaped: new effect class + `RulesEngine` method), not
        the standing-permanent replacement-clause shape the other three
        families used.
      - A differently-scoped counter-doubling clause (Innkeeper's
        Talent's "on a permanent or player") and a compound colour/type
        filter (Mechanized Warfare's "a red or artifact source") — both
        fail closed today, deliberately not guessed.
      - The full RULE 616.1 "if X would Y, Z instead" grammar beyond the
        five fixed sentences shipped so far (more real formulations —
        target/duration variants).
      - A land's own "spend only on a spell of the *chosen* creature
        type/color" mana-spend variant (Cavern of Souls, Unclaimed
        Territory, Throne of Eldraine) and a mana-value-threshold clause
        (Helga, Troyan) — unrecognized, fail-soft.
      - No split-choice UI for "any combination of colours", and no
        button for hand-zone mana abilities yet
        (`frontend/ToDo_Frontend.md`).
      - monarch/initiative (deferred per M6), prohibition/cost-
        modification statics, and emblems remain unmodeled.
- [~] Combat blocking + creature-vs-creature damage: **engine + keywords
      done** — see
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)". Remaining: an *interactive*
      blocker-declaration UI (opponent-side, needs the multiplayer
      priority loop).
- [ ] Feature gaps surfaced by hand-authoring the "Wyleth Equip" Boros
      voltron commander deck (`game/ability_catalogue.py`) — see
      [docs/implementation-state/ToDo_EdgeCases.md](../docs/implementation-state/ToDo_EdgeCases.md)
      "Equipment / Auras / 'combat damage to a player' triggers" for the
      full list of affected cards. The reusable primitives that *did* ship
      from that work (mass "destroy/exile all X [with a toughness/mana-
      value filter]" board wipes, the `"attached_permanent"`/
      `"self_or_attached_permanent"` trigger-subject family + a
      `EventType.DAMAGE` `"filter"` predicate for "deals combat damage to a
      player", Living Weapon/Renown behavior, a per-count static-anthem
      multiplier, RULE 702.8b Flash now gating `GameEngine.can_cast`'s
      timing check) are narrated in
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)". Still open, each a real feature rather than
      a narrow edge case:
      - No phasing subsystem (RULE 702.26) at all.
      - No mechanism threads a spell's announced `{X}` (`StackItem.x`,
        stored but never read by `resolve_top_of_stack`) into a one-shot
        effect's amount/count.
      - No hand-zone, non-mana "discard this card: `<effect>`" (Channel)
        activated ability, and no Cycling (RULE 702.29/28.2h).
      - No "look at top N cards, take one matching a filter, bottom the
        rest" mechanic, distinct from a whole-library `search`.
      - No "exile cards and you may play them until end of turn" (impulsive
        draw) mechanic.
      - No per-cast, board-state-dependent cost reduction for a card still
        in hand (only a battlefield permanent's static "spells cost {N}
        less" exists, `continuous.cost_reduction_for`).
      - No "flash if `<condition>`"/"activate loyalty at instant speed if
        `<condition>`" conditional casting/activation permission (plain,
        unconditional Flash *is* now wired into `can_cast`).
      - A per-firing dynamic reference to "that creature"/"the object this
        same effect just created" has no channel into a bind-on-load
        `TriggeredAbility` (one fixed `effects` list reused every firing) —
        the same class of gap `RulesEngine.check_rampage` routes around by
        not using `TriggeredAbility` at all; nothing this batch needed has
        gotten that bespoke treatment yet.
- [~] Static abilities / continuous-effects layer system (RULE 613):
      **engine done** — full layer coverage (1-7, timestamp ordering,
      bounded RULE 613.8 dependency ordering) — see
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)". The goldfish UI has an optional,
      default-hidden layer/static panel showing the trace.

      "Become a copy of target permanent/creature" (RULE 706/707, incl. the
      layer-1 continuous form) shipped — moved to
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)".

## Card-type & structural coverage (Backlog)

Card *kinds* the engine doesn't model as anything beyond a generic
permanent/spell. None block goldfishing a typical deck, but each is a
clause the future oracle parser (docs/09) or a dedicated handler must
eventually own. Roughly in decreasing commonness:

- [~] Double-faced & modal-DFC cards (RULE 712): **transform on the
      battlefield, modal-DFC back-face cast/play, a generic transform
      trigger/effect, and day/night (RULE 731) + daybound/nightbound (RULE
      702.145) are all done** — see `docs/implementation-state/
      Done_Backend.md` "Card-type & structural coverage". Remaining:
      bespoke *conditional* transform triggers ("look at the top card…, if
      instant/sorcery, transform" — Delver of Secrets) aren't modeled (a
      genuinely new "reveal + conditional" one-shot family); the legacy
      pre-2021 non-daybound werewolf template ("if no spells were cast last
      turn, transform ~") is deliberately not modeled, superseded by RULE
      731; and MDFC commanders cast from the command zone are a known,
      deliberately unhandled edge case (only hand-cast offers both faces).
- [ ] Saga (RULE 714) / Class (RULE 716) / Leveler (RULE 711) residual
      edges — the mechanics themselves are done (`docs/implementation-state/
      Done_Backend.md` "Card-type & structural coverage"); these are left
      `UNMODELED`/fail-closed rather than guessed: a Class level combining
      both a static "cumulative" grant and a separate one-shot "when this
      Class becomes level N" trigger in the same block; a level-block body
      using a trigger phrase/effect family the oracle parser doesn't
      already recognize (independent of this work — e.g. "creature deals
      combat damage to a player"); CDA-based Leveler P/T (``*/*``, no card
      in the pool needs it); a Leveler's rare non-keyword *base*
      (pre-`LEVEL`) ability line (parsed ungated).

      Copying objects (RULE 707, token copies + "becomes a copy of") shipped
      — moved to
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Card-type & structural coverage".
- [ ] Battles (RULE 310) and Dungeons (RULE 309) — new type lines with
      their own attack/venture subsystems.
- [ ] Niche/format extras: Emblems (RULE 114), Stickers (RULE 123), the
      Monarch (RULE 725) / Initiative (RULE 726), Rad counters (RULE 728),
      and the remaining multiplayer/casual variants (CR 8, CR 9 beyond
      Commander). Deprioritized until a deck needs one.

## Game Engine (Phase 3) — remaining

- [~] Multiplayer game session + priority system (UC4): **priority
      primitive built** (`GameEngine.pass_priority(player)`, RULE 117.3-4/
      APNAP) — see
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Game Engine (Phase 3)". Still **stubbed**:
      `GameSessionManager.create_multiplayer` raises
      `MultiplayerNotImplementedError` and `POST /api/game/multiplayer`
      returns 501 — the session/route need to drive `pass_priority(player)`
      and expose the priority holder, and interactive blocker declaration
      (`declare_blockers`, engine-ready) needs the opponent-side UI.

## LLM Deck Analysis (UC2)

- [ ] `POST /api/decks/{id}/analyze`: Claude API integration, prompt
      templates, structured output parsing, caching (docs/02 UC2,
      docs/04 Phase 6). `Deck.analysis_id` is already reserved to link a
      saved deck to whatever this produces — no `Analysis` model/table
      exists yet, design that alongside this endpoint rather than
      assuming the reserved field's shape is final.

## Auth & persistence

- [ ] User accounts, login/signup (docs/04 PART 4 REST endpoints).
- [ ] No user accounts yet, so saved decks aren't scoped to an owner —
      anyone hitting the API sees every saved deck. Revisit once auth
      exists.
- [ ] Game history / session persistence.

## Bot AI (UC5)

- [ ] Greedy bot strategy (docs/02 UC5) — a start exists in
      `GameEngine.run_goldfish_turn`/`auto_play_step` (play a land, tap
      out, cast cheapest-first, swing); a real bot would weigh lines.
