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

      **Library-top / impulsive-draw permissions:**
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

      **Triggers / grants:**
      - Group-subject damage triggers ("a creature you control deals
        combat damage to a player", as opposed to the shipped self-subject
        shape).
      - "Sacrifice `<name>` unless you pay `<cost>`" — the single biggest
        remaining upkeep-trigger template (45 cards); needs a real
        interactive pay-or-lose-it choice, not just recognition.
      - Quoted granted *phase/upkeep* triggers — "~ has 'at the beginning
        of your upkeep, …'"-shaped quoted-ability grants still fail closed;
        controller-scoped phase triggers work for a card's own top-level
        ability but not yet when granted onto another permanent via a
        quoted-ability clause.
      - Aura ETB effects ("when ~ enters, tap enchanted permanent") and
        "return this Aura to hand" triggers aren't modeled.
      - Standing granted protection — "all creatures have protection from
        black"/"…from the chosen color" as a *standing* (non-"until end of
        turn") grant; `combat.is_protected_from` only reads printed text
        plus a one-shot `temp_protections` set, no layer-6 "standing
        granted protection" concept exists yet.
      - Extending a chosen-type/color choice (RULE 601.2b) beyond the
        battlefield — "creatures you control are the chosen type in
        addition to their other types" (Arcane Adaptation) and "each
        creature card in your graveyard has the chosen creature type"
        (Ashes of the Fallen) both extend past the battlefield-only
        layer-4 `type_change` that's shipped.
      - A quoted **mana**-ability grant's inner "Add `<X>`" effect isn't
        recognized — "Elves you control have '`{T}`: Add `{B}`.'" (Tyvar
        Kell-shaped) and "Other permanents you control have '`{T}`: Add one
        mana of any color.'" both still fail closed via the new
        `grant_activated_ability`/`_quoted_ability_grant_effects` path
        (shipped alongside this entry), since a plain top-level mana
        ability is claimed-without-a-spec by `segmenter.py` (covered
        directly by `game/mana_abilities.py`'s recognition instead of the
        `EffectRegistry` pipeline) — so the nested recursive parse gets no
        spec at all for a granted mana ability and correctly refuses to
        guess. Needs its own small branch in `_quoted_ability_grant_effects`
        (`static_handlers.py`) that recognizes a bare "Add `<mana>`" inner
        body directly (mirroring `handlers.py`'s own `_add_mana`/
        `_ADD_MANA_RE`) and emits `grant_mana_ability` (already shipped,
        hand-authored-only today, `game/effects.py`) instead of
        `grant_activated_ability` — not a new engine primitive, just the
        missing text-recognition front end for an existing one. Found while
        shipping the activated-ability grant above: a **pre-existing**
        `segmenter.py` bug (`_ACTIVATED_RE`'s cost group was quote-blind, so
        a quoted grant's own inner colon was stealing the match before any
        grant handler ever ran) meant this exact shape was silently
        swallowed as a no-op — not recognized *or* honestly UNMODELED —
        wherever the cost-sniff (`_COST_LOOKS_REAL`) happened to accept the
        bogus quote-truncated "cost". Fixed as part of shipping the
        activated-ability grant (`_ACTIVATED_RE` now excludes `"`), which
        correctly flipped every affected card to UNMODELED — this bullet is
        what closes them for real.

      **Combat statics:**
      - Qualified/conditional combat-restriction variants — "can't be
        blocked by/except `<filter>`", "can't attack unless …", "…alone",
        "…unless they're mana abilities" all still fail closed (only the
        unqualified can't-attack/can't-block/can't-be-blocked/
        attacks-if-able shapes shipped). Separately, the large family of
        *targeted, resolve-time* "target creature can't block this turn"
        activated/triggered effects is a different shape entirely (a
        one-shot effect, not a standing static) and hasn't been attempted.

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
      - "Manifest dread" / "open an attraction" — new subsystems, distinct
        from Monarch/Initiative/Emblem (shipped).
      - Jin-Gitaxias-style compound activation condition — "…and only if
        you have seven or more cards in hand" stacked on top of
        sorcery-speed timing; the whole clause fails closed rather than
        silently dropping the second condition.

      **Replacement effects / mana:**
      - `prevent_damage`'s two real cards (Riot Control/Thought Lash) — a
        one-shot *spell effect* granting a temporary shield
        (Regenerate-shaped: new effect class + `RulesEngine` method), not
        the standing-permanent replacement-clause shape the other three
        families used.
      - The full RULE 616.1 "if X would Y, Z instead" grammar beyond the
        five fixed sentences shipped so far (more real formulations —
        target/duration variants).
      - Lurrus of the Dream-Den's own "if a spell cast this way would be
        put into a graveyard this turn, exile it instead" — a standing
        replacement scoped to *spells cast via this permission this turn*
        (not the whole card, not the whole turn); the graveyard-cast
        permission itself (`graveyard_cast_permission`,
        `game/graveyard_cast.py`) is shipped and the card is `MODELED` on
        that alone, but this trailing clause isn't modeled, so a permanent
        recast this way and later destroyed will incorrectly return to the
        graveyard instead of exile.
      - A land's own "spend only on a spell of the *chosen* creature
        type/color" mana-spend variant (Cavern of Souls, Unclaimed
        Territory, Throne of Eldraine) and a mana-value-threshold clause
        (Helga, Troyan) — unrecognized, fail-soft.
      - No split-choice UI for "any combination of colours", and no
        button for hand-zone mana abilities yet
        (`frontend/ToDo_Frontend.md`).
      - `{E}` (energy) pips in cost text are silently ignored, not
        modeled as the energy-counter mechanic
        (`costs.parse_activation_cost`, `game/costs.py`).
      - "Add 1 mana of any color" is left unclaimed — the mana-symbol-run
        handler only claims a *pure* run of `{colour}` symbols (fail-closed)
        since which color is a player choice the parser doesn't yet
        express (`parser/oracle/catalogue/handlers.py`'s `_add_mana`/
        `_ADD_MANA_RE`).

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
- [ ] Battles (RULE 310) and Dungeons (RULE 309) — new type lines with
      their own attack/venture subsystems. Initiative's own "venture into
      the dungeon" trigger (RULE 726.2) depends on Dungeons landing first —
      see `Done_Backend.md` "Card-type & structural coverage" for what
      Initiative already does without it.
- [ ] Niche/format extras: Stickers (RULE 123), Rad counters (RULE 728), and
      the remaining multiplayer/casual variants (CR 8, CR 9 beyond
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
- [ ] Manual trigger-ordering combined with a targeted/optional trigger in
      the same ordered set isn't handled. A trigger placed via the opt-in
      RULE 603.3b interactive-ordering choice (`resolve_trigger_order_
      choice`) is placed directly and does not pause for its own
      target/"you may" choice. Both features work individually; only the
      combination is untested/unhandled. (`RulesEngine._place_triggers`.)

## Oracle parser: long-tail strategy & family-level gaps

Full-universe coverage (`scripts/coverage_report.py`, ledger-backed via
`services/coverage_db.py`): 23.5% (8,041/34,209 cards) as of 2026-07-20,
PARSER_VERSION 18. The remaining ~26k single-card templates are, by construction, not
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

## cEDH staples cube

Cards from a cEDH cube pool left `UNMODELED`/unregistered, grouped by the
one engine primitive each is blocked on (a card appears once, under its
blocker). Each is a specific gap, not a vague "too hard".

- **Two independent targeting effects on one ability** — see the Equipment
  entry above (Brass Squire, Halvar God of Battle, Archdruid's Charm).
- **Interactive "pay `{cost}` or lose the game" at a delayed step** —
  Summoner's Pact / Pact of Negation. Corpse Dance separately needs
  Buyback + reanimation + a baked delayed-exile target.
- **"If no mana was spent to cast it" mana-spent tracking** — Lavinia,
  Azorius Renegade (plus its own dynamic cast-prohibition) / Boromir,
  Warden of the Tower (plus the Ring).
- **"Who was dealt combat damage by ~ this turn" history** — Hope of
  Ghirapur.
- **"Return another permanent you control that shares a type" choice** —
  Cloudstone Curio.
- **Buyback alt-cost** — Reiterate.
- **Interactive per-opponent "may pay `{2}`" + reflexive copy** —
  Wandering Archaic.
- **Bounce-spell-to-hand effect alongside a spell copy** — Narset's
  Reversal.
- **Dynamic produced-mana amount** ("add one mana of any type that
  permanent produced") — Kinnan, Bonder Prodigy.
- **Triggered mana ability** (RULE 605.1b/605.4 — must resolve immediately
  into the pool, not via the stack, so its extra mana is spendable in the
  same payment) — Wild Growth.
- **Tap-all-matching-lands mana denial** — Mana Web.
- **Second dynamic-value source from a sacrificed permanent** —
  `StackItem.x` only threads a spell's announced `{X}`; nothing stashes an
  additional cost's sacrificed permanent (or its MV) for a resolving
  effect to read: Eldritch Evolution, Neoform.
- **"Choose a card name" input + dig-until-match loop** — no primitive lets
  a player name an arbitrary card before a zone is examined, nor exiles
  from the top until a filter matches: Demonic Consultation, Possibility
  Storm (also needs to intercept every player's every hand-cast), Tibalt's
  Trickery (also needs a secret-simultaneous-number choice for Wheel of
  Misfortune-style effects — hidden multiplayer info).
- **Control-*exchange* primitive** — `control_change` (layer-2 static) and
  `CopyPermanentEffect` are the only control/copy shapes; neither swaps two
  permanents' controllers: Gilded Drake.
- **Repeat-until-condition loop** — no effect keeps going until a predicate
  over what's happened so far is met: Helm of Obedience.
- **Open-ended "as many times as you choose" loop** — every existing loop
  has a fixed or player-capped count: Lim-Dûl's Vault.
- **Fading (RULE 702.32)** — no "enters with N fade counters, remove one
  each upkeep or sacrifice" mechanic: Tangle Wire.
- **Devotion count-selector** — `continuous.count_selector` has no
  devotion entry: Thassa's Oracle.
- **Whole-board phasing** — the phasing mechanism (`GameObject.
  phased_out`) is scoped to a single permanent; nothing phases out every
  permanent a player controls plus the player: Teferi's Protection.
- **Soulbond (RULE 702.94)** — bare `FLAG` keyword only, no pairing logic:
  Deadeye Navigator.
- **Mutate (RULE 702.140)** — no merge/casting implementation, no
  `EventType.MUTATE`: Lore Drakkis.
- **Bargain additional cost** — bare `FLAG` keyword only, no
  additional-cost handling or "was it bargained" flag: Beseech the Mirror.
- **Giver of Runes' "another" restriction** — no "other creature you
  control" target kind yet for the shipped grant-protection path.
- **Dress Down's ETB draw + end-step self-sacrifice**, and **Underworld
  Breach's "escape" grant** — both ride the shipped board-wide
  ability-strip static but need their own separate extension.
- **Dynamic/count-driven mana amount + cross-graveyard "cards named X"
  selector** — `AddManaEffect` adds a fixed symbol list, and
  `count_selector` has no "cards named X across every graveyard" entry:
  Rite of Flame.
- **Per-count activation-cost reduction** — `activation_cost_reduction_for`
  supports a flat amount but no per-count formula (mirroring
  `cost_reduction`'s `per` param): Eiganjo, Seat of the Empire ("{1} less
  per legendary creature"; registered with the Channel ability at full
  cost, the reduction dropped).
- **Blood Moon's layer-6 ability-removal half** — "Nonbasic lands are
  Mountains" overwrites subtype + grants `{R}` (layer 4) but doesn't strip
  a land's independently-printed mana ability; no pool card needs the
  distinction yet.
- **Inline two-way modal with no bulleted header** — the modal grammar
  only recognizes the bulleted RULE 700.2 block, not a compact "A or B"
  sentence: Pemmin's Aura ("{1}: enchanted creature gets +1/-1 or -1/+1").
- **Conditional search destination** — `SearchLibraryEffect` allows one
  fixed destination per search, not "onto the battlefield tapped if a
  land, else to hand": Archdruid's Charm's first mode.
- **"Put cards from hand onto the battlefield" + Entwine** — every "put
  onto the battlefield" shape moves from a graveyard or library, never an
  open choice from hand; Entwine also has no parser recognition: Tooth and
  Nail.
- **Assorted bespoke multi-ability cards** each combining several gaps
  above or their own one-off mechanic, left fully unmodeled: Professor
  Onyx, Jeska Thrice Reborn, Tevesh Szat Doom of Fools, Mana Vault
  (optional-cost/state-conditioned upkeep + draw-step triggers), Dauntless
  Dismantler (`{X}{X}{W}`-costed mass-destroy-by-X).

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
