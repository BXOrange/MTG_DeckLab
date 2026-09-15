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
  recognition (residue after four increments).** `temp_unblockable`/the
  `"unblockable"` effect key already exist end to end
  (`game/effects/attachments_transforms.py`, `registry.py`). **Four
  increments shipped** (PARSER_VERSION 387/394/401/402, +24/+4/+15/+25,
  zero regressed each — see `Done_Backend.md`'s "Combat" section for
  exactly what each closed, incl. the third increment's own mid-batch
  correction: a first cut of the subtype-target widening was a closed,
  per-phrase word list — replaced with a fix to the *shared*
  `static_handlers.object_filter` instead, which also caught and fixed a
  real latent bug it exposed, a filter that could never match named
  `"1/1"`; and the fourth increment's own discovery, mid-diagnosis, that
  a *whole trigger-condition category* — "whenever you discard/cycle a
  card" — was missing despite both underlying events being fully
  engine-ready, only 1 of its +25 cards actually counted in this ticket's
  own search phrase; a stray edit had also briefly mis-marked this ticket
  "closed" with a false "0 UNMODELED remaining" claim on 2026-09-15 —
  corrected after `parser_probe.py` disproved it). **61 SOLO cards
  confirmed still open at PARSER_VERSION 402** (re-run `parser_probe.py
  blocked "can't be blocked this turn"` before starting — the count moves
  every batch). This ticket
  bundles roughly a hundred independently-shaped small gaps under one
  search phrase by design (see the "2026-09-15 Commander-legal tail
  sweep" preamble above — an *indefinite sweep*, not a batch with an end
  date); closing it to zero SOLO is not one sitting's work. Categorized
  residue, none of it attempted yet:
  - a delayed-trigger "…at the beginning of the next end step, return
    that creature to its owner's hand[, `<tail>`]" compound — the
    six-card Alora cycle (Alora, Cheerful Assassin/Mastermind/Scout/
    Swashbuckler/Thief; Alora, Rogue Companion), each with its own
    distinct conditional tail (life loss/token/perpetual buff/Treasure/
    perpetual debuff) — likely `create_delayed_trigger` plus a
    per-card "if you do, `<effect>`" composition, not one shared row.
  - a family of "you may `<effect>`. if you do, `<payoff>`" triggers
    (Biblioplex Kraken/Gravelgill Scoundrel/Tidal Terror/Saprazzan
    Breaker/Shrouded Serpent/Smart Ass/Gollum, Scheming Guide) whose
    antecedent is itself a resolving effect ("return another creature you
    control to its owner's hand", "tap another untapped creature you
    control", "mill a card") rather than a cost payment —
    `_PAY_COST_THEN_GENERAL_RE`'s existing "you may `<cost>`. if you do,
    `<effect>`" machinery is cost-shaped only (`_MAY_COST_THEN_CLAUSE`'s
    closed vocabulary: mana/sacrifice/discard/life/evidence/forage/
    blight), so even the simplest possible pairing ("you may return a
    creature. if you do, draw a card.") fails closed today — confirmed
    directly, not assumed. A genuinely new "optional effect, then a
    conditional follow-up keyed on whether it happened" composition, not
    a parser-only widening.
  - an activation-cost-reduction/frequency rider on the ability that
    grants unblockable (A-Sewer Crocodile/Sewer Crocodile's "this ability
    costs `<cost>` less to activate if there are 5 or more mana values
    among cards in your graveyard" — a *conditional flat* discount,
    unlike `ActivationCost.dynamic_reduction`'s existing per-unit-count
    shape, so it needs a new cost-reduction field, not just a parser row;
    Basim Ibn Ishaq's "this ability triggers only once each turn" paired
    with an unrelated second gap below).
  - "historic spell" is missing from the `SPELL_CAST` trigger's
    `spell_card_types` vocabulary (Basim Ibn Ishaq's own "whenever you
    cast a historic spell, draw a card." — confirmed even the "draw a
    card" half fails alone) even though "historic" already has real
    recognition elsewhere in this codebase for an unrelated (cost-
    modifier) shape — a parser-recognition widening, not a new primitive,
    but its own separate small ticket-worth of work.
  - a "becomes a N/M [color] [type] creature until end of turn" compound
    (Dimir Keyrune/Creeping Tar Pit/Chromium, the Mutable/Riverfall
    Mimic) — confirmed the *base* animation shape (no unblockable tail at
    all) doesn't parse standalone either, despite v388's changelog citing
    a similar-sounding family as already shipped; re-diagnose the exact
    gap (likely a two-card-type "artifact creature"/color+type
    combination the existing animation row doesn't cover) before assuming
    this is a one-line widening.
  - a qualified "…except by `<filter>`" evasion form combined with a
    multi-word type/color union filter `object_filter` doesn't support
    yet (Firefright Mage's "except by artifact creatures and/or red
    creatures" — a type-OR-color union, not a single subtype/colour/
    keyword `object_filter` already handles) or a count-based exception
    (Unquenchable Fury's "except by 2 or more creatures" — a blocker
    *count* requirement, not a characteristic filter at all; `object_
    filter` currently mis-parses this as a bogus subtype rather than
    failing closed — a latent bug worth fixing independently of this
    ticket even though nothing routes real text through it yet).
  - at least two cards (Brotherhood Spy, Devourer of Memory, both
    already-working `_pump_unblockable` effect bodies) whose real blocker
    is an unrelated trigger-condition gap incidentally sharing this
    search phrase — a conditional phase trigger ("if you control a
    legendary Assassin") for Brotherhood Spy, and "whenever 1 or more
    cards are put into your graveyard from your library" (a library-to-
    graveyard mill-adjacent event, not a discard) for Devourer of Memory.
    (Cunning Survivor, which used to sit in this same bucket on "whenever
    you cycle or discard a card," is now closed — that whole trigger-
    condition category, `EventType.DISCARD_CARD`/`CYCLED` via
    `segmenter._PLAYER_TRIGGER_CONDITIONS`, shipped PARSER_VERSION 402,
    +25 cards, only one of them actually counted in this ticket's own
    search phrase — see `Done_Backend.md`'s PAR-79 entry.)
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
