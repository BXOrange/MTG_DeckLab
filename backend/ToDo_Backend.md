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
      - "You may look at the top card of your library any time" itself is
        now claimed by the parser (a documented no-op — purely
        informational, `parser/oracle/segmenter.py`'s
        `_LOOK_AT_TOP_ANY_TIME_RE`) — but the *actual* play/cast-from-top
        permission clause it always sits next to ("You may play lands
        and/or cast spells [with mana value N or greater] from the top of
        your library") still has **no parser-front-end recognition at
        all** — the engine capability exists (`game/top_library.py`,
        `top_library_permission` `EffectSpec`, Done_Backend.md "Rules
        Engine (Phase 2)") but only via hand-authoring (Oracle of Mul
        Daya, Glarb, Calamity's Augur); a card whose only unclaimed line
        is this one (Elsha of the Infinite, Bolas's Citadel) still fails
        the coverage gate. Teaching a handler to recognize the permission
        clause generically (mirroring `top_library_permission`'s existing
        `look`/`play_lands`/`cast_spells`/`min_mana_value` params) would
        unblock it and any future card with this wording — plus each
        card's own conditional tail is a *further*, separate gap (Elsha's
        "if you cast a spell this way, you may cast it as though it had
        flash" needs a new `conditional_flash`-condition key scoped to
        "cast from the top of your library" rather than the existing
        `entered_this_turn`; Bolas's Citadel's "pay life equal to its mana
        value rather than pay its mana cost" is a different alternative-
        cost shape from the flat/free ones modeled so far).
      - `prevent_damage`'s two real cards (Riot Control/Thought Lash) — a
        one-shot *spell effect* granting a temporary shield
        (Regenerate-shaped: new effect class + `RulesEngine` method), not
        the standing-permanent replacement-clause shape the other three
        families used.
      - "Impulsive draw" (exile a card and grant *temporary* permission to
        cast/play just that card) now has a generic mechanism —
        `ImpulsiveDrawEffect`/`RulesEngine.exile_with_play_permission`/
        `GameState.temp_play_permissions` (Light Up the Stage-shaped:
        exile from own library-top, playable until end of your next
        turn) — see Done_Backend.md "Rules Engine (Phase 2)". Ragavan,
        Nimble Pilferer and Mnemonic Betrayal still stay `UNMODELED`
        though: Ragavan exiles from *the damaged player's* library (not
        its own controller's) and additionally grants "spend mana as
        though it were mana of any color," and Mnemonic Betrayal exiles
        from a graveyard rather than a library-top — both need a small
        extension to the mechanism, not a new one from scratch
        (see `docs/implementation-state/ToDo_EdgeCases.md` "cEDH staples
        cube").
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
      - Monarch/Initiative/Emblems now modeled (Card-pool Batch 10 — RULE
        725/726/114); prohibition/cost-modification statics remain
        unmodeled. RULE 725.4/726.4 ("if the monarch/initiative-holder
        leaves the game, the active player inherits it") and RULE 726.2's
        "venture into the dungeon" companion trigger (dungeons, RULE 309,
        aren't modeled at all) are still open — see the Dungeons entry below.
      - Leyline's "As long as this card is in your opening hand, you may
        begin the game with it on the battlefield" (Card-pool Batch 8,
        investigated and deferred) — a pregame mulligan/setup-phase
        permission, not a battlefield static or resolve-time spell effect,
        so it doesn't fit the `EffectRegistry`/binder pipeline at all; it
        needs a new "opening hand → battlefield" step in
        `services/game_session.py`'s `_mulligan`/`keep_hand` flow instead.
- [~] Combat blocking + creature-vs-creature damage: **engine + keywords
      done** — see
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)". Remaining: an *interactive*
      blocker-declaration UI (opponent-side, needs the multiplayer
      priority loop).
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
      their own attack/venture subsystems. Initiative's own "venture into
      the dungeon" trigger (RULE 726.2) depends on Dungeons landing first —
      see `Done_Backend.md` "Card-type & structural coverage" for what
      Initiative already does without it.
- [ ] Niche/format extras: Stickers (RULE 123), Rad counters (RULE 728), and
      the remaining multiplayer/casual variants (CR 8, CR 9 beyond
      Commander). Deprioritized until a deck needs one. (Emblems/RULE 114
      and the Monarch/Initiative designations, RULE 725/726, shipped —
      Card-pool Batch 10, moved to `Done_Backend.md`.)

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
