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
      coverage gate). Everything shipped so far — the RULE 702 keyword
      catalogue + flag-keyword binding, the effect-clause front-end
      (`normalize`/`segmenter`/`catalogue/handlers`/`gate.py`), one-shot
      families (damage/draw/discard/destroy/gain_life/counter/mill/
      exile/tap/+1-1-1-counters/tokens/pump/scry/bounce/graveyard-
      recursion/tutor/add_mana/mass-damage/ETB-self-attach), static/
      anthem/lord clauses (subtype/token/colour/global scoping,
      attached-permanent statics), landwalk + replacement-effect +
      parametric-keyword binding, RULE 614.1 enters-tapped claiming (all
      variants) + enters-with-N-counters, RULE 603.1 trigger-condition
      scoping, the counter family (spell target filters/"unless pays"/
      "can't be countered"), modal spells (spell- and triggered-ability-
      level), additional cast costs, "up to one target" (N=1), the
      kicked-spell additional-effect conditional, 3 of 5 replacement
      families, regenerate, surveil, parse-on-load memoization, and the
      full mana-ability rewrite (spend restrictions RULE 605.3a, "any
      combination of colours" RULE 605.1a, hand-zone mana abilities,
      Leveler-gated mana, Deathrite Shaman) — is in
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)". `parser/oracle/processing_list.py`
      tracks cache-wide coverage; run `coverage_over_cards()` for the
      current number before quoting one (21.4% as of 2026-07-16).

      **Still open:**
      - A real "up to two/three/N"/"up to X" multi-target choice (N>=2 —
        an interactive multi-select and per-effect application over a
        *list* of targets, materially larger than the N=1 case shipped).
      - "Choose <n> —"/"choose <n> or more —" (a bigger modal-header
        grammar than RULE 700.2's "choose one"/"choose one or both" — an
        interactive multi-*mode* selection, not a target choice) is the
        current top processing-list blocker.
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
      primitive built; session wiring remains**. `GameEngine.pass_priority`
      now takes an optional `player`: called with one (RULE 117.3-4) it only
      resolves the top of the stack once every living player has passed in
      succession, hands priority to the next player (APNAP, `_advance_priority`)
      otherwise, and any real action reclaims priority (`give_priority`, called
      from `begin_turn`/`_run_step`/`play_land`/`cast_spell`/`activate_ability`).
      `GameState.priority_passed` tracks who has passed and deep-copies for
      rewind. Called with no `player` it keeps the old solo/goldfish
      auto-resolve, so nothing regresses. Tests: `test_priority.py`. Still
      **stubbed**: `GameSessionManager.create_multiplayer` raises
      `MultiplayerNotImplementedError` and `POST /api/game/multiplayer` returns
      501 — the session/route need to drive `pass_priority(player)` and expose
      the priority holder, and interactive blocker declaration
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
