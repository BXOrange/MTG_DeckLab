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

## PAR — Parser

- **PAR-12 · The indefinite long tail (methodology pointer, not a closeable
  ticket).** Strategy, coverage, worked examples, and the Commander-legal
  tail sweep (`scripts/commander_tail_report.py`'s bucket taxonomy, and
  everything `PAR-31…PAR-53` ever tracked) all live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) now — not here, and not as a
  second, separate quasi-ticket the way `PAR-31…PAR-53` used to sit
  alongside this one. Parser coverage is an *indefinite standing project
  goal*, not a batch with an end date — that was already true of this
  entry, and `PAR-31…PAR-53` was never really a different kind of thing,
  just a differently-prioritized slice of the identical indefinite sweep
  (Commander-legal-first instead of raw-cache-first). Folded together
  2026-09-15 so the split matches what each half actually is, not
  historical accident. Two tracks: **basic mechanics** (generic shapes,
  cache-wide yield) — the raw-cache `rank`-driven pass was exhausted
  2026-08-28, but re-entering through `commander_tail_report.py`'s Bucket B
  (below) found a second wave of real, individually-verified wins the same
  day (PAR-78/PAR-79 alone are 65- and 105-card clusters) — **don't repeat
  "exhausted" from stale prose without re-running the tool** — and
  **set-specific mechanics** (a set/precon's signature keyword, worked
  deck-first against a saved deck). Planechase/Archenemy plane/scheme card
  *bodies* fold in here too (triggers already recognized, ~13/309 bodies
  done) — not a separate ticket.

  > **Ticket-id note:** every number from `PAR-1` through `PAR-92` is
  > already a real, shipped-or-open, cross-referenced ticket — grep
  > `Done_Backend.md` before reusing one (`PAR-14`, for one, is RULE
  > 603.2's once-per-turn trigger limiter, nothing to do with keywords).
  > `PAR-31…PAR-53` was this cluster's own reserved id block (see
  > [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) for what shipped under it).
  > `PAR-74…PAR-92` is the 2026-09-15 Commander-legal tail sweep filed
  > below, each individually confirmed via `parser_probe.py blocked`
  > against PARSER_VERSION 386. The first free parser ticket id is
  > **`PAR-93`** (checked 2026-09-15). A genuinely new engine primitive
  > found along the way (missing behaviour, not just a parser gap) still
  > files as its own real, closeable `MEC-*` ticket below — that part of
  > the sweep stays in this file, since a primitive is schedulable work
  > with an end state, unlike the sweep itself.

### 2026-09-15 Commander-legal tail sweep — Bucket B (recurring templates)

Every count below is `parser_probe.py blocked` SOLO-blocker output against
PARSER_VERSION 386 on 2026-09-15 — re-run before starting, per this
project's own standing rule that a ranked count goes stale the moment it's
read. Several of these were flagged by `commander_tail_report.py` as
"missing primitive" but turned out, on grep, to already have one (RULE
613.4d `pt_switch`, the `unblockable`/`temp_unblockable` grant, the
"all"-amount `prevent_damage_shield`) — filed as `PAR-*` parser gaps, not
`MEC-*`, for exactly that reason. Ordered by verified SOLO count.

- **PAR-79 · "`<Name>`/target creature can't be blocked this turn" — broad
  recognition (residue after nine increments).** `temp_unblockable`/the
  `"unblockable"` effect key already exist end to end
  (`game/effects/attachments_transforms.py`, `registry.py`). **Nine
  increments shipped** (PARSER_VERSION 387/394/401/402/403+404/405+406+407/410/411/412,
  +24/+4/+15/+25/+32/+90/+13/+4/+5, zero regressed each — see `Done_Backend.md`'s
  "Combat" section for exactly what each closed). The fifth through ninth
  increments are a different *kind* of fix from the first four: diagnosing
  individual SOLO cards (`parser_probe.py card`) showed most of the
  residue's real blocker wasn't the `unblockable` effect at all — an
  unrecognized trigger *condition*, filter, or composition shape sat in
  front of an already-parseable clause — so they worked those layers
  instead, applying the extend-parser skill's newly-documented "decompose
  into atomic grammar units" rule (`reference/handler-recipe.md`). The
  sixth increment also found and fixed a genuine **dormant engine bug**:
  RULE 613.4b's layer-5 colour-changing static existed with zero
  `EffectRegistry` factory ever reaching it (nothing in the codebase could
  construct one) — every affected card would have parsed `MODELED` while
  silently never changing colour at runtime, caught by an execute test,
  not the parse-level ones. **v408 is a same-ticket cleanup, +0/+0**: the
  two dedicated "another target attacking creature"/"[another ]target
  legendary creature" rows shipped in earlier increments turned out to be
  the exact "enumerate phrase variants instead of fixing the axis" shape
  `handler-recipe.md` warns about — `object_filter` now strips a leading
  "attacking"/"legendary"/"blocking"/"tapped" flag word itself, so both
  rows became a strict subset of the general "target `<object-filter
  phrase>`" row and were deleted rather than kept as dead duplicates (see
  `PARSER_LONG_TAIL.md`'s "Lessons that keep recurring" for the writeup).
  The seventh increment closed the sixth's own three named motivating
  cards (Biblioplex Kraken/Gravelgill Scoundrel/Tidal Terror), which had
  turned out to still be unparseable even after `_may_effect_then` shipped
  for them — see `Done_Backend.md`'s "Combat" section for the dormant
  `_peel_optional` guard bug this uncovered. The eighth increment closed
  four of the six-card Alora, Cheerful `<X>` cycle (Assassin/Mastermind/
  Swashbuckler/Rogue Companion) by widening the already-shipped MEC-52
  `_DELAYED_SAC_EXILE_WHEN_FIRST_RE` (sacrifice/exile "when-first" siblings)
  with a "return" verb branch and an "if you do" tail collapsed into the
  same `create_delayed_trigger`'s own effects list, plus a new dispatch for
  an unrelated earlier sentence in front of the delayed clause; Cheerful
  Scout/Thief remain open (see `Done_Backend.md` for exactly why).
  **46 SOLO cards confirmed still open at PARSER_VERSION 412** (unchanged
  by the ninth increment, which closed a related but separate cluster
  outside this search phrase — see below; re-run
  `parser_probe.py blocked "can't be blocked this turn"` before starting —
  the count moves every batch). This ticket
  bundles roughly a hundred independently-shaped small gaps under one
  search phrase by design (see the "2026-09-15 Commander-legal tail sweep"
  preamble above — an *indefinite sweep*, not a batch with an end date);
  closing it to zero SOLO is not one sitting's work. Categorized residue,
  grouped by what it actually needs:
  - **Needs a new composition primitive at real cluster size:**
    - the Alora, Cheerful `<X>` cycle's own delayed-trigger-with-payoff
      compound — **4 of 6 closed by the eighth increment**
      (`_DELAYED_SAC_EXILE_WHEN_FIRST_RE`'s "return" verb + "if you do"
      tail, `create_delayed_trigger`'s existing `capture="previous_or_
      self"`; no new primitive needed after all). Cheerful Scout ("if you
      do, it perpetually gets +1/+1") and Cheerful Thief ("if you do, a
      creature of your choice an opponent controls perpetually gets
      -1/-0") remain: both tails name the returned creature ("it") or open
      a *fresh* untargeted opponent-choice pick — the "if you do" clause is
      parsed independently of the antecedent's own `previous_or_self`
      capture (a deliberate scope limit of the eighth increment, not a bug
      — see `Done_Backend.md`), so a pronoun or a second interactive choice
      inside that clause isn't reachable yet. Wings of Hubris/Goblin
      Sappers print the unrelated **tail-form** "…at/at end of combat,
      sacrifice/destroy `<permanent>`" shape on an *activated* (not
      triggered) ability, preceded by their own unblockable-grant sentence
      — `_DELAYED_SAC_EXILE_TAIL_RE` has no equivalent of the eighth
      increment's new prefix-dispatch (`segmenter._PREFIXED_DELAYED_SAC_
      EXILE_RE`, when-first-only) for the tail form, confirmed still
      UNMODELED — a real, separate widening, not attempted this pass.
    - the **targeted** sibling of the seventh increment's own "return/tap
      another `<X>` you control" fix, now split into three real,
      independently-scoped pieces after the ninth increment (PARSER_VERSION
      412, `_RETURN_TO_HAND_KINDS` widened with the already-whitelisted
      `other_creature_you_control` — see `Done_Backend.md`) closed the
      plain form (Deputy of Acquittals/Jeskai Barricade, +3 bonus cards
      elsewhere in the cache). **6 SOLO cards confirmed still open**
      (`parser_probe.py blocked "you may (return|tap) (another|2 other|
      two other) .*you control"`, re-run before starting):
      - Guardians of Koilos ("another target **historic** permanent")/
        Stockpiling Celebrant ("another target **nonland** permanent") —
        `resolve_target_kind` doesn't recognize either qualifier combined
        with "another…you control" at all (confirmed via direct check,
        not just a `_RETURN_TO_HAND_KINDS` gap) — a real but small
        `subgrammars.py` widening, not attempted this pass.
      - Niambi, Esteemed Speaker ("if you do, you gain life equal to that
        creature's mana value.") — the plain targeted return itself would
        now parse (ninth increment), but its own "if you do" follow-up
        names the just-returned creature's mana value, a referent this
        engine has no baked-target-then-measure-it composition for on a
        genuine RULE 115 target (the untargeted `previous_or_self`/
        `create_delayed_trigger` baking mechanism the eighth increment
        used doesn't apply here — there's no delay, and the target is
        gone from the battlefield by the time "if you do" would read it).
      - Meanders Guide ("you may tap another untapped merfolk you
        control. when you do, return **target** creature card … from your
        graveyard to the battlefield.") — an untargeted antecedent (the
        seventh increment's own fix) but a *targeted* follow-up, which
        `_may_effect_then` correctly declines (the same "no announced-
        target step for an off-stack effect list" reasoning as everywhere
        else in this family) — needs the same targeted-follow-up
        composition as Niambi, not a widening of `_may_effect_then` itself.
      - First Responder ("you may return another creature you control to
        its owner's hand, **then** put a number of +1/+1 counters equal to
        that creature's power on ~.") — untargeted antecedent, but "then"
        (not "if you do") and a magnitude reading the just-returned
        creature's *power* rather than gating on success at all; a
        different composition shape, not part of either bucket above.
      - Indoctrination Attendant's own antecedent ("return another
        permanent you control…") already routes through the seventh
        increment's fix as expected — confirmed via `parser_probe.py card`
        that its real, sole blocker is instead the "if you do" token-
        creation tail itself ("create a 1/1 … token with toxic 1 and
        '~ can't block.'"), a compound "printed keyword count **and** a
        quoted static ability" token-creation shape with no grammar of its
        own yet — unrelated to this bucket, filed here only so a future
        pass doesn't re-diagnose it as the same targeted-return gap.
  - **Needs an interactive mechanic this engine doesn't model at all** —
    Blufferfish's true/false bluffing guess, Smart Ass's hidden-information
    reveal-or-not, Gollum's card-guessing minigame. Out of a parser
    ticket's scope; each would need its own new `RulesEngine`/
    `continuations` primitive first.
  - an activation-cost-reduction/frequency rider on the ability that
    grants unblockable (A-Sewer Crocodile/Sewer Crocodile's "this ability
    costs `<cost>` less to activate if there are 5 or more mana values
    among cards in your graveyard" — a *conditional flat* discount,
    unlike `ActivationCost.dynamic_reduction`'s existing per-unit-count
    shape, so it needs a new cost-reduction field, not just a parser row).
    Separately, `ActivationCost.dynamic_reduction`'s existing "for each
    `<count_selector>`" shape has **zero oracle-text recognizer at all**
    despite being fully engine-ready — a real 37-SOLO-card cluster found
    while investigating this (`parser_probe.py blocked "this ability
    costs \{"`), worth its own ticket.
  - a much larger, separate "mana **spent** to cast (not printed mana
    value)" threshold family — the plain total-threshold half (Colorstorm
    Stallion/Deluge Virtuoso/Elemental Mascot/Exhibition Tidecaller/
    Expressive Firedancer/Molten-Core Maestro/Muse Seeker/Phoenix of
    Iteration, "cast an instant/sorcery, get a bonus; if 5+ mana was
    spent, upgrade it") now has its engine predicate
    (`spell_mana_spent_at_least`, sixth increment) but still needs a
    reusable "if `<condition>`, `<effect>` instead/also" intervening-if
    peel on a trigger body (today only built as one-off whole-line regexes
    per exact combination, `_COUNTER_FREE_SPELL_RE`). RULE 702.140
    **Adamant** ("if at least three `<color>` mana was spent to cast this
    spell, `<bonus>`" — Ardenvale/Embereth/Garenbrig/Locthwain Paladin,
    Foreboding Fruit, Outmuscle) is completely unbuilt (`grep -ri adamant`
    finds nothing) and needs *per-colour* spent-mana tracking the
    `SPELL_CAST` event doesn't carry (only the total `mana_spent` the
    sixth increment's predicate reads). Worth its own ticket.
  - a qualified "…except by `<filter>`" evasion form on the **mass/
    subtype-scoped** unblockable ("each minotaur can't be blocked this
    turn except by 2 or more creatures", Unquenchable Fury) — the sixth
    increment's `any_of`/`min_blockers` widenings both landed on the
    *targeted* form (`_cant_be_blocked_turn`); the mass form
    (`_cant_be_blocked_turn_mass`) has no subtype scope or except-by tail
    at all, and `UnblockableEffect.selector` is a closed name enum
    (`continuous.group_selector_objects`), not a filterable selector —
    confirmed a true singleton via `parser_probe.py blocked
    "^each [a-z]+ can't be blocked this turn"`.
  - a "becomes a N/M creature until end of turn" compound with **no
    colour word at all** (Creeping Tar Pit's "becomes a 3/2 blue and black
    elemental creature. it's still a land. it can't be blocked this
    turn." — actually needs the *leading* "until end of turn," word order
    plus a separate-sentence unblockable tail, not just colours; Chromium,
    the Mutable's "becomes a human with base power and toughness 1/1,
    loses all abilities, and gains hexproof" is a wholly different
    template, `_BASE_PT`-shaped not `_ANIMATE_SELF`-shaped) — the sixth
    increment's colour/subtype widening closed every *same-template* card
    (Dimir Keyrune, the whole Keyrune/Monument cycles, +57 total); these
    two are separately-shaped residue, not more of the same gap. Riverfall
    Mimic's own sibling ("whenever you cast a spell that's both blue and
    red, …") needs a two-colour AND cast-trigger filter —
    `_CAST_SPELL_TRIGGER_RE`'s `types`/`cast_of_color` slots are single-
    colour only.
  - "target creature **you cast a spell that targets** a creature" (Snooping
    Page — a cast-trigger filter reading whether the cast spell had a
    creature among its targets; `SPELL_CAST`'s existing `targets_a_
    permanent`/`target_instance_ids` fields, built for Tiller of Flesh,
    are close but permanent-typed, not creature-typed), a dynamic
    "power X or less" target filter tied to an activation's own paid X
    (Minamo Sightbender/Runed Arch), and an intervening-if on an
    *attached-subject* ATTACKS trigger reading the attacker's **own**
    power ("if its power is 2 or less", Writ of Passage — the existing
    `attacked_player_has_most/lowest_life` gates read the *defender's*
    life, a different subject entirely) are each their own separate small
    parser-recognition gaps, not yet attempted.
  - at least two cards (Brotherhood Spy, Devourer of Memory, both
    already-working `_pump_unblockable` effect bodies) whose real blocker
    is an unrelated trigger-condition gap incidentally sharing this
    search phrase — a conditional phase trigger ("if you control a
    legendary Assassin") for Brotherhood Spy, and "whenever 1 or more
    cards are put into your graveyard from your library" (a library-to-
    graveyard batch event distinct from `EventType.MILL_CARD`'s existing
    per-card firing, RULE 603.3f — over-fires if modeled naively off the
    per-card event) for Devourer of Memory.
  - a genuinely large, separate, tournament-legal RULE 715 mechanic with
    zero recognition today: "whenever you crank this Contraption" — 45
    SOLO cards on its own (Top-Secret Tunnel's own trigger). Unfinity's
    Contraptions are *not* the silver-border non-goal (Wizards ships them
    tournament-legal); this is a whole unbuilt sub-mechanic (the crank
    event, sprocket/target-number resolution), not a one-line widening —
    its own ticket.
  - assorted true one-off bodies better suited to
    `game/ability_catalogue.py` hand-authoring than more parser grammar
    (Kamiz, Obscura Oculus's connive-then-choose-lesser-power compound;
    Sewers of Estark's attacking-or-blocking branch; Wedding Invitation's
    target-subtype-conditional lifelink tail; Long River Lurker's ETB-
    target-then-delayed-exile-and-return; Atomic Microsizer's equip-
    trigger choose-then-animate compound; Zhuge Jin's "before attackers
    are declared" activation-timing restriction; Dreadlight Monstrosity's
    "activate only if you own a card in exile" activation condition;
    Secret Tunnel's "share a creature type" multi-target filter; Open into
    Wonder's X-count multi-target plus a quoted-grant tail on "those
    creatures"; Trygon Prime's "counter on it AND on target X" compound
    dual-counter body — none yet attempted).
- **PAR-80 · X-spell "target creature gets +X/+`<N>` until end of turn."**
  (residue after one increment). The variable-power/fixed-toughness pump
  family — turned out to need no new primitive at all:
  `RulesEngine._substitute_x` already walks any bound effect's own
  `power`/`toughness` for the literal `"x"`/`"-x"` sentinel, and
  `PumpEffect.amount_from_count_selector`/`_axis` already read a live
  board count on one or both axes. **First increment shipped**
  (PARSER_VERSION 395, +20, zero regressed) — `_pump_target_x`/
  `_PUMP_TARGET_X_RE` (the bare X-spell/X-ability form, with an optional
  "and gains `<keyword>`" tail) plus `_pump_target_x_selector`/
  `_PUMP_TARGET_X_SELECTOR_RE` (a closed "where X is `<phrase>`" table:
  `creatures_you_control`, `creature_cards_in_your_graveyard`,
  `cards_in_your_hand`, `life_gained_this_turn`, the five basic-land-type
  counts). **19 SOLO cards confirmed still open** (re-run `parser_probe.py
  blocked "target creature gets \+x/\+"` before starting), each a distinct
  new amount referent this increment's phrase table doesn't cover:
  - "the greatest mana value among permanents you control" (Accelerated
    Mutation, Boon of Boseiju) / "the greatest power among creatures you
    control" (Oaken Power Suit) — no `continuous.count_selector` entry for
    either "greatest `<X>` among" reading yet.
  - "the number of counters on permanents you control" (Hydra Trainer);
    "the number of cards revealed this way" (Ivy Seer, Scent of Ivy — a
    resolve-time count of an earlier clause's own reveal, not a board
    state); "3 plus the number of cards named `<name>` in all graveyards"
    (Muscle Burst); "a number from 0 to 6 chosen at random"/"the result"
    of a die roll (Hapato's Might, Growth Spurt) — each its own referent.
  - "its power"/"that creature's power" (Onward // Victory, Rush of
    Blood, Nantuko Mentor, Wine of Blood and Iron) — the pumped *target's
    own* current power, not the source's (`amount_from_count_selector=
    "source_power"` already exists but reads the wrong object).
  - "the revealed card's mana value" (Planeswalker's Favor) — a
    resolve-time referent off a just-revealed card, not a board count.
  - Accessories to Murder/Oaken Power Suit's own "whenever you crank this
    contraption" trigger condition is a separate, unrelated recognition
    gap (Contraption cranking) that happens to share this search phrase —
    verify which clause is the real blocker before assuming this family
    closes them.
- **PAR-82 · Quoted static grants — the remaining SOLO cards on
  "creatures you control have"/"enchanted creature has" (residue; the
  ticket's own original premise was stale).** Re-verified 2026-09-15: both
  subject shapes **already work** — `static_effect_specs('creatures you
  control have "when ~ enters, draw a card."')` and the "enchanted
  creature has" equivalent both correctly resolve to `affects=
  "creatures_you_control"`/`"attached_permanent"` today, confirmed
  directly against `_QUOTED_GRANT_RE`/`_ATTACHED_QUOTED_GRANT_RE`. Every
  card still SOLO on either search phrase is blocked by its **own
  unrelated inner-ability gap** instead — closing one doesn't touch any
  other, so don't build a shared fix expecting it to sweep the list.
  **One closed this pass**: Phenax, God of Deception's own granted "{T}:
  target player mills X cards, where X is this creature's toughness." —
  `MillEffect.count_selector`'s already-shipped `"source_power"`/`"source_
  toughness"` reading (`continuous.count_selector`, evaluated against the
  effect's own bound `source` — the *granted-to* creature once regranted,
  not the enchantment/permanent that printed the ability) just needed a
  parser row (`_mill_source_pt`/`_MILL_SOURCE_PT_RE`). Re-run
  `parser_probe.py blocked 'creatures you control have "'`/`'enchanted
  creature has "'` before picking the next one — 13 SOLO cards remain,
  each its own separate primitive/recognition gap:
  - Kira, Great Glass-Spinner: "whenever ~ becomes the target of a spell
    or ability for the first time each turn, counter that spell or
    ability." — `BECOMES_TARGET` + "for the first time each turn" both
    already parse; the blocker is "counter that spell or ability" itself,
    a `CounterSpellEffect` referent for "whatever `BECOMES_TARGET` just
    named" that doesn't exist yet.
  - Nadu, Winged Wisdom: same `BECOMES_TARGET` trigger, but "this ability
    triggers only twice each turn" — `trigger.limit` is currently a bare
    once-per-turn flag, not a count.
  - Regal Sliver: "`<pump>` if you're the monarch. otherwise, you become
    the monarch." — an `is_monarch`-gated `if_else` joining two genuinely
    different effect types (pump vs. `become_monarch`); confirmed neither
    half parses today even alone (the "if you're the monarch" conditional
    pump clause fails closed on its own).
  - Retaliation ("whenever ~ becomes blocked by a creature, …" — no
    "became blocked" trigger event yet, only `BLOCKS`/attacker-side);
    Spiteful Sliver ("whenever ~ is dealt damage, it deals that much
    damage to…" — no "this permanent was dealt damage" trigger event);
    Tale of Katara and Toph ("whenever ~ becomes tapped for the first
    time during each of your turns…" — no `TAPPED` trigger event at all).
  - Ghired, Mirror of the Wilds (copy a token that entered this turn);
    Katilda, Dawnhart Prime (a mana ability reading the *granted-to*
    object's own printed colors); Animal Friend (counting Auras/Equipment
    attached to the granted-to creature, excluding itself); Bewitching
    Leechcraft (an untap-step replacement effect); Custody Battle
    (upkeep "gain control unless you sacrifice a land"); Mark of Sakiko
    (combat-damage-triggered mana that doesn't empty at end of step);
    Sisay's Ingenuity (a resolve-time interactive "becomes the color of
    your choice" chooser) — each its own real, separately-scoped gap; none
    share enough shape with another in this list to close together.
- **PAR-83 · "`<cost>`: put target card from a graveyard on the bottom of
  its owner's library."** A new one-shot effect verb, distinct from the
  existing shuffle-into-library family — no shuffle involved, straight to
  bottom. Confirmed: 12 SOLO, 2 also-blocked. Chrome Companion, Cogwork
  Archivist.
- **PAR-84 · Tap-and-skip-next-untap family.** Two grammatical shapes of
  the same underlying effect: a static/one-shot form ("tap up to N target
  creatures. those creatures don't untap during their controller's next
  untap step.") and a triggered form ("whenever ~ deals combat damage to a
  creature, tap that creature and it doesn't untap during its controller's
  next untap step."). Confirmed: 11 + 7 = 18 SOLO combined (14 + 9 total).
  Adverse Conditions, Chilling Grasp; Kashi-Tribe Reaver, Kashi-Tribe
  Warriors.
- **PAR-85 · Self-protective damage redirect.** "The next N damage that
  would be dealt to `<name>` this turn is dealt to target creature you
  control instead." Distinct from the already-shipped
  `RequestRedirectDamageSourceEffect` (which redirects damage from a chosen
  *source*) — this is a fixed-amount, fixed-recipient (self) redirect to a
  different chosen creature. Confirmed: 5 SOLO, 1 also-blocked. The en-Kor
  cycle: Lancers en-Kor, Nomads en-Kor, Outrider en-Kor.
- **PAR-86 · "Target player shuffles up to N target cards from their
  graveyard into their library."** Confirmed: 6 SOLO, 1 also-blocked.
  Dwell on the Past, Gaea's Blessing, Krosan Reclamation.
- **PAR-87 · Additional cost "sacrifice a creature or pay `<cost>`."** An
  OR-form additional cost between a sacrifice and a mana payment.
  Confirmed: 5 SOLO, 0 also-blocked. Bayou Groff, Eaten Alive, Lash of the
  Balrog.
- **PAR-88 · "You may play lands from your graveyard" — static
  permission.** Same shape as the existing "play from top of library"
  permission (`game/top_library.py`) but for the graveyard zone. Confirmed:
  5 SOLO, 5 also-blocked. Crucible of Worlds, Ramunap Excavator, Perennial
  Behemoth.
- **PAR-89 · ETB-with-named-counter cycles.** Four small, structurally
  identical cycles: enters tapped with N charge counters (Vivid lands),
  enters tapped with N depletion counters, and two Kamigawa Myojin cycles
  that enter with a divinity/indestructible counter only if cast from
  hand (the cast-from-hand condition already exists as a referent
  elsewhere — verify before treating as new). Confirmed: 5 + 5 + 3 + 2 =
  15 SOLO combined, all clean. Vivid Crag, Hickory Woodlot, Myojin of
  Cleansing Fire, Myojin of Blooming Dawn.
- **PAR-90 · Suspect-state as a resolve-time/condition referent.** RULE
  701.60's `is_suspected` flag already exists
  (`game/effect_conditions.py`, `game/static_conditions.py`); these cards
  read it from effect bodies the parser doesn't yet wire to it — a draw
  bonus conditioned on "if the sacrificed creature was suspected," a Case
  solve-condition ("you control no suspected skeletons"), and clauses that
  clear the flag ("it's no longer suspected"). Confirmed: 11 SOLO, 1
  also-blocked. Agency Coroner, Case of the Stashed Skeleton, Eliminate the
  Impossible, Frantic Scapegoat.
- **PAR-91 · "Evidence was collected" as a resolve-time conditional
  referent.** Collect Evidence is already largely built (`game/isa.py`,
  `effects/choices_actions.py`, `condition_query.py`,
  `rules/misc_mixin.py`); these two need "if evidence was collected" wired
  as a conditional-magnitude/cost-reduction gate, the same shape as the
  existing kicked/teamwork conditional family. Confirmed: 2 SOLO, 14
  also-blocked on unrelated clauses — Bite Down on Crime, Lamplight
  Phoenix are the two clean ones.
- **PAR-92 · Small verified residue batch.** Five independent,
  already-confirmed small fixes — bundle as one batch rather than five
  tickets:
  - "The second spell you cast each turn costs `<cost>` less to cast." — 3
    SOLO (Alisaie Leveilleur, Highspire Bell-Ringer, Monk Class).
  - "This spell costs `<cost>` less to cast for each basic land type among
    lands you control." — 3 SOLO (Draco, Leyline Binding, Scion of Draco).
  - "If `<name>` would be put into a graveyard from anywhere, reveal
    `<name>` and shuffle it into its owner's library instead." — 5 SOLO, 0
    also-blocked (Blightsteel Colossus, Darksteel Colossus, Legacy
    Weapon).
  - "Triple that/target/its `<amount>`" — a straight 3× sibling of the
    already-shipped "double" multiplier (RULE 701.11); 1 SOLO (Triple
    Threat).
  - Meld triggered by a specific game event (attacking together) rather
    than the already-shipped upkeep-check shape — 1 SOLO (Mishra, Claimed
    by Gix); Titania, Voice of Gaea needs the same widening plus one
    unrelated clause.

  > `commander_tail_report.py --min-cluster 5`'s Bucket B histogram
  > (2026-09-15) still lists ~30 more N=5-6 templates not individually
  > verified above — re-run `parser_probe.py blocked` on each before
  > filing a ticket for one. This sweep's own check of "you get an emblem
  > with `<name>`" (57 total appearances) came back only **1 SOLO**,
  > confirming `PARSER_LONG_TAIL.md`'s standing warning that a raw ranked
  > count overstates real yield.

## MEC — Game mechanics

### 2026-09-15 Commander-legal tail sweep — Bucket D (missing primitive)

Each confirmed via `parser_probe.py blocked` (2026-09-15, PARSER_VERSION
386) after grepping `game/` to rule out an existing primitive first — two
of `commander_tail_report.py`'s own bucket-D labels ("no dice subsystem at
all", "ISA gap: meld") turned out to be stale (a dice subsystem and meld
both already shipped, MEC-75/MEC-77); see MEC-90's own note. Ordered by
verified SOLO count.

- **MEC-89 · "Tapped and attacking" battlefield entry (RULE 508.3).** A
  token or returned/reanimated creature entering the battlefield already
  flagged as attacking (a specific player or planeswalker) has no engine
  primitive — nothing lets an object join `CombatState`'s attacker list
  outside the declare-attackers step. Confirmed via `parser_probe.py
  blocked "tapped and attacking"`: 63 SOLO (84 total) — the single biggest
  cluster in this whole sweep. Needs a combat-mixin primitive that adds an
  object to the current combat as an attacker of a chosen defender, taps
  it (unless the card's own wording grants an exemption), and fires the
  same attack-trigger consequences a normally-declared attacker would.
  Adeline, Resplendent Cathar; Alesha, Who Smiles at Death;
  A-Thousand-Faced Shadow; Altaïr Ibn-La'Ahad.
- **MEC-90 · Dice-roll result as a resolve-time amount (RULE 706).**
  MEC-75 shipped the roll-and-branch mechanism (`RollDieEffect`), but no
  downstream effect can read "the result" as its own `amount` — "gain
  life/create N tokens/put N counters/draw N cards equal to the result"
  all still fail. `commander_tail_report.py`'s "no dice subsystem at all"
  label is stale (verify before trusting it, per this project's own
  standing rule) — the real gap is a new `amount_from_dice_roll` referent
  in `game/effect_amounts.py`, alongside the already-shipped
  `amount_from_trigger_event`/`count_from_trigger_event` family, reading
  the value `RollDieEffect` already produces. Confirmed: 45 SOLO (90
  total). Adorable Kitten, Ancient Brass/Bronze/Copper/Gold/Silver Dragon.
- **MEC-91 · "Dealt damage by `<source>` this turn" tracker.** A
  per-source, per-turn record of which objects a specific permanent dealt
  damage to this turn — feeds "can't be regenerated," death/reanimation,
  and flip triggers scoped to one damage source; distinct from the generic
  damage-dealt-this-turn totals already used elsewhere. Confirmed via
  `parser_probe.py blocked "dealt damage by ~ this turn"`: 11 SOLO, 0
  also-blocked — clean. Mirror the pattern of
  `GameContext.objects_exiled_this_way`. Bone Shaman, Bushi Tenderfoot //
  Kenzo the Hardhearted, Dread Slaver, Krovikan Vampire.
- **MEC-92 · Exchange control / exchange life totals.** Two related
  one-shot primitives, neither implemented: (a) swap `Player.life` between
  two players outright (grep for an existing life-swap effect before
  building — none found as of this sweep), and (b) exchange control of two
  target permanents simultaneously, including across two different
  controllers — distinct from an ordinary gain-control effect since both
  permanents change hands in the same event. Confirmed via
  `parser_probe.py blocked "exchange control of|exchange the control|
  exchange life totals"`: 9 SOLO (10 total). Get a Life, Magus of the
  Mirror, Mirror Universe, Kitsune, Dragon's Daughter.
- **MEC-93 · Clash (RULE 701.16).** Zero engine support today. Reveal the
  top card of your library and have an opponent do the same; compare mana
  values, the higher wins (a tie means no one wins); each player may put
  their own card back or leave it revealed on top depending on the calling
  card's text. Confirmed via `parser_probe.py blocked
  "\bclash(?:es|ed)?\b"`: 3 SOLO, 0 also-blocked. Small cluster but a
  genuine RULE-defined keyword action. Merfolk Surveyor, Scattering
  Stroke, Sentry Oak.
- **MEC-94 · Face a Villainous Choice.** An opponent-facing (not
  caster-facing) binary modal choice — the affected player, not the
  spell's controller, picks between two named consequences. Distinct from
  the existing caster-side modal-spell machinery. Confirmed via
  `parser_probe.py blocked "villainous choice|face a villainous"`: 3 SOLO
  (6 total). Midnight Crusader Shuttle, Sycorax Commander, This Is How It
  Ends.
- **MEC-95 · Incubate (RULE 701.71).** Create a face-down Incubator token
  carrying N +1/+1 counters that can later be turned face up (transformed)
  into a copy of its source creature. No existing primitive. Confirmed via
  `parser_probe.py blocked "\bincubate[sd]?\b"`: 1 clean SOLO (Incubob).
  Brimaz, Blight of Oreskos and Sunder the Gateway also match "incubate"
  but each need a second, unrelated clause too — this ticket only needs to
  cover the primitive itself.
- **MEC-96 · Waterbend `<cost>` alternative-cost verb (low priority).** A
  distinct alternative-cost-payment keyword ("waterbend {N}" instead of
  paying a mana cost/activation cost), from the paper-legal *Avatar: The
  Last Airbender* set. Confirmed via `parser_probe.py blocked
  "\bwaterbend(?:s|ing)?\b"`: 2 SOLO, 0 also-blocked. Genuinely new but
  tiny and single-set — pick up opportunistically rather than scheduling a
  dedicated batch. Aang's Iceberg, Hama, the Bloodbender.

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
