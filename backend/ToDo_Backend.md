# Backend TODO

Open backend items only — a single merged backlog (formerly split across
this file and a `docs/implementation-state/` pointer copy; that copy no
longer exists, this file is the sole source now). **When an item is finished, move its narrative into the
matching section of [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
(section headers here mirror there) instead of leaving it `[x]` in place.**

**Keep this file worklog-free.** It's a list of open items, not a history —
don't leave "shipped"/"now modeled"/"moved to Done_Backend.md" announcements
sitting here once work is done; delete the line (or the now-closed part of
it) outright instead. If a line still has real open scope left, keep only
that part. This file is read in full fairly often (by humans and Claude), so
a stale announcement or a finished item left `[x]` in place re-bloats every
future read and defeats the point of the split.

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
      tracks cache-wide coverage; run `scripts/coverage_report.py` for the
      current number rather than trusting a figure quoted here or in
      CLAUDE.md.

      **Targeting / multi-target / counters:**
      - Cross-target constraints: Run Away Together's own two-sentence
        "Choose two target creatures controlled by different players.
        Return those creatures to their owners' hands." stays unclaimed —
        a different, indirect-referent grammar shape ("choose target(s)
        [+ constraint]. Verb those [referent]s.") the parser front-end has
        no recognition for at all, even though `ReturnToHandEffect` itself
        already accepts `distinct_controllers` (`targeting.TargetSpec.
        distinct_controllers`, the single-sentence "N target X controlled
        by different players" shape *is* claimed for `destroy`/`exile` —
        Protector of the Wastes-shaped). Also unrelated and still open: 2+
        *different* targeting effects on one spell/ability sharing a
        target list *is* fixed — `StackItem.target_groups`,
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
        pattern `gameBoardView.js` already uses.
      - Price of Betrayal's "remove up to five counters from target
        artifact, creature, planeswalker, **or opponent**" compound target
        (a player alongside three permanent types) stays unclaimed — a
        different, wider target-kind-union gap than the shipped
        `RemoveCountersEffect.max_count` chosen-amount shape itself (which
        already covers plain "target permanent"/"target creature").

      **Statics / scopes:**
      - **Non-creature group scopes.** `static_handlers._scope` only ever
        claims *creature* scopes ("goblins you control", "white creatures",
        "all creatures"), so every anthem/keyword-grant/quoted-ability-grant
        family it feeds fails closed on "Other **enchantments** have '…'"
        (Aura Flux), "**Artifacts** you control get …", etc. The layer
        engine itself is ready — `continuous.group_selector_objects` already
        has `artifacts_you_control`/`permanents_you_control`/
        `nonland_permanents_you_control`/`all_permanents`/`all_lands`
        selectors — so this is parser-side only: `_scope`/`_scope_params`
        need to return a card-type-scoped `affects` instead of returning
        `None`, keeping the existing `_NONCREATURE_TYPES` block-list only
        for the *anthem* family (a "+N/+N" clause really does only make
        sense on creatures).
      - **RULE 702.16e's "This effect doesn't remove this Aura." tail.**
        Six of the eight "protection from the chosen color" Auras
        (Flickering Ward, Cho-Manno's Blessing, Pentarch Ward, Benevolent
        Blessing, Floating Shield, Ward of Lights) print this trailing
        sentence on the same line as the grant, and it leaves them
        UNMODELED even though the grant itself is now modeled. It's *not*
        safe to claim as a no-op: it reads as one only because this engine
        doesn't implement RULE 704.5n (an SBA unattaching an Aura its host
        has protection from) at all — see the related "re-validate an
        existing attachment's legality every SBA pass" item below. Build
        that SBA and this exception together, or the exception becomes a
        silent landmine.
      - **"As ~ enters, choose a *basic land* type."** (RULE 601.2b) —
        `static_handlers._CHOOSE_CREATURE_TYPE_ON_ENTER_RE` and the colour
        sibling are the only two enter-choice shapes; the basic-land-type
        one needs its own option list (Plains/Island/Swamp/Mountain/Forest)
        in `RulesEngine._offer_enter_choices`. Blocks Realmwright and
        A-Thran Portal, whose *type-grant* halves are otherwise modeled.

      **Combat statics:** fully shipped — see Done_Backend.md, "Combat
      statics" for the qualified/conditional restriction family, the RULE
      509.1c/d requirement family, the RULE 509.1b multi-block permission
      family, and the two closing parser-only gaps (a count-selector
      threshold instead of a literal int; a group scope with its own
      power/toughness qualifier). "…unless its controller pays `<cost>`"
      (Brainwash/Propaganda-shaped) was never part of this section — it
      belongs to the prohibition/cost-modification entry under
      "Designations / setup" below.

      **Cost-keyword mechanics:**
      - Kicker `{X}`'s own paid-X variant (Emblazoned Golem, 1 card).
      - Granting Cycling to other cards ("each card in your hand has
        cycling {2}") — a static-grant shape, not a keyword-recognition
        one.
      - Generic Cycling execution for an unregistered card — the
        `discard_self` activated-ability primitive exists, but binding a
        bare oracle-recognized "cycling" keyword spec into a real
        activatable ability is still hand-authored per-card only.
      - True face-down Morph/Megamorph *execution* (casting face-down as a
        2/2, turning face up) — a real new permanent-state subsystem (see
        also "Face-down permanent states" under Card-type coverage below).
      - Strive — not a RULE 702 keyword ability in this codebase's
        catalogue at all; a per-extra-target cost escalation needing its
        own new grammar.
      - Monstrosity / Adapt (~63 cards) — needs a new
        `GameObject.is_monstrous`-style flag plus a "becomes
        monstrous/adapted" trigger event and its own effect types; a clean
        separate mechanic, not an extension of the firebreathing-pump
        family.

      **New subsystems (unattempted):**
      - Fight (~40 cards across templates) — "target creature you control
        fights target creature …" (RULE 701.?) has no `FightEffect` at
        all; a good future-batch candidate.
      - "Manifest dread" — a new subsystem, distinct from
        Monarch/Initiative/Emblem (shipped). (Attractions, RULE 717, are a
        permanent project non-goal like Stickers (RULE 123) — not a gap,
        never to be built.)
      - Jin-Gitaxias-style compound activation condition — "…and only if
        you have seven or more cards in hand" stacked on top of
        sorcery-speed timing; the whole clause fails closed rather than
        silently dropping the second condition.

      **Designations / setup:**
      - Prohibition/cost-modification statics remain unmodeled. RULE
        725.4/726.4 ("if the monarch/initiative-holder leaves the game, the
        active player inherits it") and RULE 726.2's "venture into the
        dungeon" companion trigger (dungeons, RULE 309, aren't modeled at
        all) are still open — see the Dungeons entry below.
      - Leyline's "As long as this card is in your opening hand, you may
        begin the game with it on the battlefield" — a pregame
        mulligan/setup-phase permission, not a battlefield static or
        resolve-time spell effect, so it doesn't fit the
        `EffectRegistry`/binder pipeline at all; it needs a new "opening
        hand → battlefield" step in `services/game_session.py`'s
        `_mulligan`/`keep_hand` flow instead.
      - An emblem's own activated ability — RULE 114.4 permits one in
        principle, but `RulesEngine.create_emblem` only files a bound
        result's `TriggeredAbility`/`StaticAbility`, silently dropping an
        `ActivatedAbility` if `bind_ability` ever returned one. No real
        emblem in the pool prints one today.

- [ ] Targeting / protection / hexproof / ward — narrow rough edges:
      - Hexproof-from-`<quality>` collapses to blanket hexproof. RULE
        702.11b's "Hexproof from red" is aliased onto the plain `hexproof`
        slug — a `FLAG`-shaped catalogue row, not `QUALITY`-shaped like
        `Protection` — so the "from X" scope is lost and the permanent is
        treated as hexproof from *everything*. Safe/overprotective (never
        lets an illegal target through), never rules-illegal, just not
        accurate. Fix: give `Hexproof` a `QUALITY` shape and regex like
        `Protection`'s. (`parser/oracle/catalogue/keywords.py`'s
        `_ALIASES`.)
      - An existing attachment's legality isn't re-validated every SBA
        pass. RULE 704.5m/n also cover a target that stays on the
        battlefield but becomes newly illegal for the attachment (e.g. an
        enchanted creature gains protection after the Aura is already
        attached) — today only "the host left the battlefield" is checked.
        (`RulesEngine._detach_attachments_from`, `game/rules_engine.py`.)
      - `SacrificeEffect` auto-picks which permanent is sacrificed.
        Annihilator's "defending player sacrifices N permanents" (RULE
        702.86) uses the same non-interactive MVP auto-choice as
        `GameEngine._sacrifice_candidate` (cost-payment sacrifice) rather
        than letting the player choose. An interactive picker is a future
        upgrade. (`SacrificeEffect`, `game/effects.py`.)
      - `CopyPermanentEffect` doesn't model copy-of-a-copy. RULE 707.2's
        "copiable values" interacting with *other* copy effects (a copy of
        a copy, layered copy effects) isn't modeled — it copies straight
        from the printed card. (`CopyPermanentEffect`, `game/effects.py`.)
      - A token copy via `create_token` never offers its own
        `enter_as_copy` choice. Unlike `resolve_top_of_stack`'s
        `_resolve_permanent_spell`, a token created with RULE
        614.1c/614.12 `enter_as_copy_effects` bound to it (a token copy of
        e.g. Clever Impersonator) never gets that choice offered
        mid-`create_token` — no real card in the pool currently needs it.
        (`RulesEngine.create_token`, `game/rules_engine.py`.)

- [ ] Layers / static abilities (RULE 613) — narrow rough edges (engine
      itself is done: full layer coverage 1–7, timestamp ordering, bounded
      RULE 613.8 dependency ordering — see
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)"; the goldfish UI has an optional,
      default-hidden layer/static panel showing the trace):
      - Layer 3 (RULE 612 text-changing) is scoped to one consumer. Built,
        but only as word-substitution over a derived
        `GameObject.effective_oracle_text` field, consumed *only* by
        `combat.protections_of_text` (Artificial Evolution's "protection
        from red" → "protection from blue") — not a full oracle-text
        re-parse, so bound abilities/keywords are unaffected by a layer-3
        rewrite. (`continuous.py`'s `text` sublayer, between layers 2 and 4.)
      - RULE 613.8 dependency ordering is bounded to one sublayer. Only
        layer 2's controller-scoped `affects` ("creatures you control") is
        ordered by dependency; every other sublayer is provably safe on
        pure timestamp order given today's effect vocabulary, but would
        need extending if a future selector could read another object's
        derived state. (`continuous._order_control_effects`.)
      - Layer 1 "become a copy" mutates in place instead of running as a
        recompute pass. `become_copy` (the permanent-ETB-copy mechanism,
        e.g. Clever Impersonator) directly mutates the object; only the
        *conditional* copy case (Vesuvan Shapeshifter) got the true
        per-`recompute` layer-1 treatment. (`game/copy_mechanics.py`,
        `game/continuous.py`.)
      - A granted trigger with no `instance_id` in its firing event isn't
        identity-scoped. A layer-6-granted triggered ability (e.g.
        Dionus, Elvish Archdruid's "Elves you control have...") is scoped
        per-grantee by the firing event's `instance_id` — but an event
        shape carrying no `instance_id` at all isn't filtered by identity.
        No card in the pool currently grants a trigger off such an event.
        (`continuous._granted_trigger_condition`.)

- [ ] Equipment / Auras / "combat damage to a player" triggers — remaining
      rough edges (the `"attached_permanent"`/`"self_or_attached_permanent"`
      trigger-subject family + `EventType.DAMAGE` `"filter"` predicate are
      done, see Done_Backend.md):
      - Two independent targets on one ability aren't supported (docs/
        Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md §5) — Brass
        Squire's "attach target Equipment to target creature", Halvar God
        of Battle's "attach target Aura/Equipment attached to a creature
        you control to target creature you control", and Archdruid's
        Charm's third mode (also a *dynamic* damage amount tied to the
        other effect's target) are all left unregistered/unmodeled rather
        than guessed at for this reason.
      - Simian Sling's "defending player" resolves off its own
        combat-defender stamp, which is only set when Simian Sling
        *itself* is the attacker — reconfigured onto a different attacking
        creature, the trigger still fires but finds no defending player to
        hit (`effects._defending_player_of`, `ability_catalogue.
        _simian_sling`).
      - A per-firing dynamic reference to "that creature"/"the token this
        effect just created" has no generic `TriggeredAbility` IR support
        for a *granted* ability (`RulesEngine.check_rampage`/`check_ward`
        do this via a bespoke "construct a fresh `TriggeredAbility` per
        firing" pattern; the shipped `TriggeredAbility.reflexive` primitive
        covers a fixed-shape reflexive target found by the firing event's
        `instance_id`, not an arbitrary grant). Kaldra Compleat's granted
        "exile that creature" and Sigarda's Aid's "whenever an Equipment
        you control enters, you may attach *it*" both hit this wall.
      - Embercleave's "costs {1} less for each attacking creature you
        control" needs a board-count-*during-declare-attackers*
        `count_selector` on the (existing) `self_cost_reduction_for`.
      - Timely Ward's "cast as though it had flash if it targets a
        commander" needs a `"targets_a_commander"` key added to
        `conditional_flash`'s condition whitelist
        (`game/condition_query.py`).

- [~] Combat blocking + creature-vs-creature damage: **engine + keywords
      done** — see
      [Done_Backend.md](../docs/implementation-state/Done_Backend.md)
      "Rules Engine (Phase 2)". Remaining: an *interactive*
      blocker-declaration UI (opponent-side, needs the multiplayer
      priority loop).

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
      731 — a permanent non-goal, not open work; and MDFC commanders cast
      from the command zone are a known, deliberately unhandled edge case
      (only hand-cast offers both faces).
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
- [ ] Prepared cards: trigger-condition recognition limited to four base
      events. A Prepared card's own "become prepared" condition only binds
      if it's one of the already-recognized trigger conditions
      (enters/dies/attacks/blocks) — a general parser gap, not specific to
      Prepared. (`segmenter.py`'s `_TRIGGER_EVENTS`.)
- [ ] Face-down permanent states (morph/manifest) aren't modeled, so the
      goldfish/Replay board's card-back-sleeve fallback for a face-down
      token with no uploaded art currently has no real trigger condition to
      fire on — real transformed DFCs keep their genuine Scryfall
      back-face art instead. (`gameBoardView.js`'s `resolveImageUrl`; see
      also `CLAUDE.md` "What this is".)
- [ ] **Battles (RULE 310)** — a new permanent type, cast like a spell
      (310.1) but attackable like a planeswalker. Zero scaffolding exists
      (`is_battle` on `Card`/`GameObject`, everything below). Scope:
      - **Defense** (310.4): a battle enters with defense counters equal to
        its printed defense (310.4b), current defense = counter count
        (310.4c), and combat/spell damage to it *removes* defense counters
        rather than being tracked separately (310.6) — reuse
        `RulesEngine._apply_entry_counters`'s existing generic
        `entry_counters(card) → add_counters(counter_type, amount)` path
        (already how Sagas' `"lore"` counters and planeswalker `"loyalty"`
        are seeded, `game/rules_engine.py:1132`), adding a `"defense"`
        counter type + a `GameObject.defense` convenience property
        mirroring `.loyalty`/`.lore` (`models/game_object.py:635-640`).
        SBA: defense 0 and no pending triggered ability from it →
        graveyard (310.7), same shape as the existing loyalty-0 SBA.
      - **Attacking a battle**: the attacker-declaration defender-spec
        pattern is already generic across `{"kind": "player"|"planeswalker"}`
        (`legal_defenders_for`/`declare_attackers`/`_assign_defender`/
        `_defender_spec`/`_same_defender` in `game/game_engine.py:1647-1754`,
        `_resolve_combat_defender` in `game/rules_engine.py:566-586`) — add a
        `"battle"` kind filtering `is_battle` instead of `is_planeswalker`
        and routing combat damage to defense-counter removal instead of
        loyalty loss. No restructuring needed, just a third branch at each
        site.
      - **Protector** (310.8–310.11): a battle has a controller *and* a
        separate protector (usually an opponent, chosen on entry for the
        only currently-real subtype, Siege — 310.11a) who is the
        "defending player" for attacks against it (310.8d) and the only
        player who can block for it (310.8c) — notably a Siege can be
        attacked by its own controller (310.8b). This is a genuinely new
        per-object field (`GameObject.protector_id`?) plus a new entry-time
        choice (mirrors the existing `pending_choice` "choose a creature
        type/color on enter" flow, `RulesEngine._offer_enter_choices`) and
        touches blocker-legality checks wherever they currently assume
        attacker's-opponent == defending player.
      - **Siege transform-on-empty** (310.11b): "when the last defense
        counter is removed, exile it, then you may cast it transformed
        without paying its mana cost" — a triggered ability off the
        counters-hitting-zero event, reusing the existing DFC
        transform/MDFC-cast machinery (`Done_Backend.md` "DFC transform +
        day/night") rather than anything new on the cast side.
      - Not attachable even if also an Aura/Equipment/Fortification (310.9,
        an edge case, no real card needs it yet).
- [ ] **Dungeons (RULE 309)** — cards that are never part of a deck, are
      brought into the game via the `venture into the dungeon` keyword
      action (701.49) into the command zone, are never permanents and
      can't be cast (309.2c), and track position with a per-player venture
      marker across the dungeon's rooms. Zero scaffolding exists. Scope:
      - **Model**: `Emblem` (`models/emblem.py`) is the closest existing
        analog — a command-zone object with no permanent representation —
        but it's a deliberate one-off, not a generic base class; a
        `Dungeon` needs its own model (current room, i.e. venture-marker
        position) plus a `Player.dungeons`-style single-slot field (309.3:
        a player owns at most one dungeon card in the command zone at a
        time). Dungeon cards themselves also need to exist as a distinct
        pool outside any deck (309.2) — not currently representable at
        all, since every card the engine knows about today comes from a
        deck or the Oracle cache keyed for deck-building.
      - **Room abilities** (309.4c): each room has a triggered ability,
        "When you move your venture marker into this room, [effect]" — the
        same *shape* as a Saga's lore-counter chapter trigger (event +
        position payload, `RulesEngine.advance_sagas` firing
        `EventType.SAGA_CHAPTER`, `game/rules_engine.py:2793`) but Saga's
        plumbing isn't reusable as-is: it needs its own new event type and
        its own parser grammar for room text (Saga's chapter-line grammar,
        `parser/oracle/catalogue/saga.py`, is a different roman-numeral
        shape). Completing a dungeon (309.7, removing it from the game at
        the bottommost room) is a new SBA (309.6).
      - **Venture into the dungeon** (RULE 701.49, the keyword action that
        brings a dungeon in / advances the marker / completes and replaces
        it) is itself a new engine primitive with no existing analog —
        needed both as a standalone effect (a card can say "venture into
        the dungeon") and to unblock Initiative's own inherent "venture
        into the dungeon" companion trigger (RULE 726.2), which is
        currently *not* fired for exactly this reason — see
        `Done_Backend.md` "Card-type & structural coverage" for what
        Initiative already does without it.
      - No dungeon cards are legal in a real constructed deck (they're
        brought in from "outside the game"), so this whole feature is
        purely additive UI/engine plumbing — nothing here can partially
        break an existing deck's coverage numbers.
- [ ] Niche/format extras: the remaining multiplayer/casual variants (CR 8,
      CR 9 beyond Commander). Deprioritized until a deck needs one.

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
- [ ] Goad (RULE 701.15) isn't modeled at all — no engine primitive, no
      parser recognition. A goaded creature "attacks each combat if able"
      (a forced-attack constraint, the same *shape* `combat.py`'s existing
      "must attack" keywords would need to enforce) "and attacks a player
      other than [the goading player] if able" — the second half needs a
      per-object "may not attack this specific player" restriction that
      doesn't exist yet either (unlike a landwalk/menace-style evasion
      restriction on *blocking*). Moved here from the closed-out "Rad
      counters" entry (`Done_Backend.md`): Acquired Mutation ("Enchanted
      creature gets +2/+2 and is goaded") is the one real card blocked on
      it, and goad is squarely a multiplayer/Commander-table mechanic (its
      whole point — forcing an attack at a *specific other* opponent — is
      inert in 1v1, where "a player other than you" only ever resolves to
      one player anyway), so it's tracked alongside this engine's other
      multiplayer gaps rather than as a standalone item.
- [ ] Manual trigger-ordering combined with a targeted/optional trigger in
      the same ordered set isn't handled. A trigger placed via the opt-in
      RULE 603.3b interactive-ordering choice (`resolve_trigger_order_
      choice`) is placed directly and does not pause for its own
      target/"you may" choice. Both features work individually; only the
      combination is untested/unhandled. (`RulesEngine._place_triggers`.)
- [ ] RULE 502.1 "you may choose not to untap ~" (`no_untap_optional`,
      `GameEngine.set_skip_untap`) has full engine + `legal_actions` +
      frontend plumbing (`gameBoardView.js`'s toggle button, shipped
      2026-07-21), but **no real printed card can reach it today**: every
      one of the ~46 real cards carrying this clause (Amber Prison,
      Rubinia Soulsinger, Hivis of the Scale, The Pandorica, …) pairs it
      with a second clause the oracle parser doesn't model yet — usually
      a "target permanent doesn't untap for as long as *this* remains
      tapped" lock-down, or a "gain control of target creature" effect —
      and `gate.parse_oracle` only ever binds a card's specs when the
      *whole* card parses (fail-closed), so the static ability itself
      never gets bound onto any of them. Modeling either family (lock-
      down-while-tapped is the more common shape, ~15+ of the 46) would
      immediately unlock this toggle for real gameplay, not just the
      hand-authored/synthetic-token test coverage that exists now
      (`tests/test_batch8_permission_statics_family.py`).

## Oracle parser: long-tail strategy & family-level gaps

Full-universe coverage (`scripts/coverage_report.py`, ledger-backed via
`services/coverage_db.py`): 25.3% (8,670/34,209 cards) as of 2026-07-22,
PARSER_VERSION 27. The remaining ~25k single-card templates are, by construction, not
generic — closing them is an *indefinite* program, not a finite batch list,
and proceeds two ways:

1. **Narrow parser extensions** for any singleton shapes that still
   generalize a little (a slightly-different targeting scope, a compound
   filter) — preferred, since each still pays off across a small cluster.
2. **Hand-authoring** genuinely unique cards in `game/ability_catalogue.py`
   (guide: `docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md`), only
   after confirming no near-miss handler would unlock a cluster of them.

`coverage_report` is re-run periodically and the loop continues against
whatever the head of the backlog is by then; the cache also grows with each
new set. A handful of items are deliberate non-goals (legacy pre-2021
werewolf template; silver-border/acorn/un-set cards) and are excluded from
the denominator or accepted as permanently unmodeled.

Deterministic-first: classification, scaffolding, and measurement are pure
code (no LLM). LLM/subagent effort (Sonnet/Haiku only, file-ownership
waves) is spent only on finalizing a handler's regex/builder semantics and
hand-authoring the tail. Keep `CLAUDE.md`'s "Implementation state" coverage
figure and the Engine-Status tab in sync after any change here.

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

## Data / cache freshness

- [ ] A stale cached row (pre-`mana_cost_string`) keeps lossy mana-cost
      data until refetched. Priced from the legacy flat pip tally +
      `converted_mana_cost` via `ManaCost.from_card` — correct
      total/colors, but hybrid/Phyrexian nuance stays unavailable for that
      row until the self-healing refetch (`Card.has_mana_cost_data`)
      happens to hit it. (`models/mana_cost.py`,
      `services/lazy_card_loader.py`.)
- [ ] The commander ban list is hand-maintained, not live-sourced.
      Scryfall's per-printing `legalities` field isn't fetched, so there's
      no live source for bans — deliberately conservative (only
      long-standing entries that survived unban waves), needs manual
      updates against the official banned-list page.
      (`services/commander_legality.py`'s `BANNED_COMMANDER_CARDS`.)
- [ ] Commander legality doesn't yet recognize Background/"Friends
      forever" pairing, or enforce that a commander must actually be
      legendary. `check_commander_legality` checks color identity, the ban
      list, and plain Partner/"Partner with X" pairing only.
      (`services/commander_legality.py`.)
