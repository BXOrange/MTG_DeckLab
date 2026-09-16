# Backlog — open work, as tickets

**The single list of open work, backend and frontend.** Replaces the former
per-half `ToDo_Backend.md` / `ToDo_Frontend.md`, which no longer exist.

Four kinds of document, kept strictly apart — put a new line in the right
one:

| Kind | Lives in | Rule |
| --- | --- | --- |
| **Open points** | this file | Only open scope. No history. |
| **Worklogs** | [Done_Backend.md](Done_Backend.md), [Done_Frontend.md](Done_Frontend.md) | Append-only. What shipped and *why it was built that way*. |
| **Examples** | [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) | Calibration samples + strategy for the indefinite parser tail. |
| **Singleton queue** | [singletons.md](singletons.md) | Genuinely one-off cards confirmed (via `parser_probe.py blocked`) to share no cluster with any other cached card — not a ticket, a queue for the `hand-author-card` skill. Never batch these into a `PAR-*`/`MEC-*` ticket; if a later sweep finds a second card sharing one's shape, promote that pair out into a real ticket instead. |

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
  tail-sweep taxonomy (`scripts/commander_tail_report.py`) all live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md), not here — `PAR-31…PAR-53`
  (folded in 2026-09-15) was never really a separate ticket, just this same
  indefinite sweep's Commander-legal-first slice. Parser coverage is a
  standing project goal, not a batch with an end date. Two tracks: **basic
  mechanics** (generic shapes, cache-wide yield — the raw-cache
  `rank`-driven pass was "exhausted" 2026-08-28, but re-entering through
  Bucket B still finds real wins, e.g. PAR-78/PAR-79's 65- and 105-card
  clusters — **re-run the tool before trusting "exhausted"**) and
  **set-specific mechanics** (a set/precon's signature keyword, worked
  deck-first). Planechase/Archenemy plane/scheme card *bodies* fold in here
  too (~13/309 done), not a separate ticket.

  > **Ticket-id note:** `PAR-1` through `PAR-98` are all taken — grep
  > `Done_Backend.md` before reusing one (e.g. `PAR-14` is RULE 603.2's
  > trigger limiter, nothing to do with keywords). `PAR-31…PAR-53` was the
  > long-tail's own reserved block (see `PARSER_LONG_TAIL.md`);
  > `PAR-74…PAR-92` is the 2026-09-15 Commander-legal sweep; `PAR-93…PAR-98`
  > is PAR-79's 2026-09-16 close-out split (its true one-offs went to
  > [singletons.md](singletons.md) instead of a ticket). First free id:
  > **`PAR-99`**. A genuinely new engine primitive found along the way
  > still files as its own `MEC-*` ticket — only the sweep itself stays out
  > of this file.
  >
  > **Anti-proliferation note:** a 2-6 card cluster is not automatically its
  > own ticket. Bundle several independently-verified small fixes into one
  > "small verified residue batch" ticket instead (PAR-92, PAR-98) — a
  > numbered sub-bullet per shape, one `PAR-*` id for the lot — and reserve
  > a standalone ticket for a cluster large enough, or mechanistically
  > distinct enough, to be worth tracking on its own. A true one-off (no
  > sibling anywhere in the cache) isn't a ticket at all — it goes in
  > [singletons.md](singletons.md) for `hand-author-card` instead. When
  > closing a large ticket surfaces a pile of small residue (as PAR-79's
  > own close-out did), triage it the same way before filing: sweep for an
  > existing ticket it already belongs under, size each shape against the
  > full cache, then batch the small ones rather than opening one ticket
  > per shape.

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
- **PAR-93 · Contraption "crank" trigger recognition (RULE 715).** A whole
  unbuilt sub-mechanic — "whenever you crank this Contraption, `<effect>`"
  (the crank event/action, sprocket/target-number resolution) has zero
  recognition today. Unfinity's Contraptions are tournament-legal (not the
  silver-border non-goal). Confirmed 45 SOLO, 0 also-blocked
  (`parser_probe.py blocked "crank this contraption"`). Accessories to
  Murder, Applied Aeronautics, Top-Secret Tunnel.
- **PAR-94 · `ActivationCost.dynamic_reduction` has zero oracle-text
  recognizer.** The engine primitive ("costs `<cost>` less to activate for
  each `<count_selector>`") is fully ready — built for hand-authored
  cards — but no parser row reaches it; every card printing "this ability
  costs `<cost>` less to activate for each `<X>`" stays UNMODELED
  regardless. Confirmed 37 SOLO, 7 also-blocked
  (`parser_probe.py blocked "this ability costs \{"`). A-Llanowar
  Greenwidow and most of the cluster.
  Separately, **not the same primitive**: A-Sewer Crocodile/Sewer
  Crocodile's own "costs `{3}` less to activate if there are 5 or more mana
  values among cards in your graveyard" is a *conditional flat* discount (a
  binary threshold, not a per-unit count) — `dynamic_reduction` has no field
  for this shape. Same ability on two database rows (an Alchemy rebalance +
  the original), so effectively one real card; decide whether a flat-if-
  condition case is worth a shared field or its own small one when this
  lands.
- **PAR-95 · RULE 702.140 Adamant.** Completely unbuilt (`grep -ri adamant`
  finds nothing) — "if at least 3 `<color>` mana was spent to cast this
  spell, `<effect>`" needs *per-colour* spent-mana tracking; today's
  `SPELL_CAST` event only carries the total `mana_spent` (built for
  PAR-79's sixth increment's `spell_mana_spent_at_least`, see
  `Done_Backend.md`). Confirmed 14 SOLO, 3 also-blocked
  (`parser_probe.py blocked "if at least [0-9]+ [a-z]+ mana was spent to
  cast this spell"`). Ardenvale/Embereth/Garenbrig/Locthwain Paladin,
  Foreboding Fruit, Outmuscle, Searing Barrage, Silverflame Ritual, Slaying
  Fire, Sundering Stroke, Turn into a Pumpkin.
- **PAR-96 · "N or more mana was spent to cast that spell" trigger-body
  upgrade.** Distinct from Adamant above (total spent mana, not
  per-colour) — the engine predicate already exists
  (`spell_mana_spent_at_least`, PAR-79's sixth increment) but needs a
  reusable "if `<condition>`, `<effect>` instead/also" intervening-if peel
  on a *trigger* body; today this shape only exists as one-off whole-line
  regexes per exact combination (`_COUNTER_FREE_SPELL_RE`). Confirmed 11
  SOLO, 0 also-blocked (`parser_probe.py blocked "if [0-9]+ or more mana
  was spent to cast that spell"`). Colorstorm Stallion, Deluge Virtuoso,
  Elemental Mascot, Exhibition Tidecaller, Expressive Firedancer,
  Molten-Core Maestro, Phoenix of Iteration, Spectacular Skywhale, Tackle
  Artist, Tellah Great Sage, Thunderdrum Soloist.
- **PAR-97 · Graveyard-batch mill trigger (RULE 603.3f).** "Whenever 1 or
  more [`<type>`] cards are put into your graveyard from your library" as a
  single batch event, distinct from `EventType.MILL_CARD`'s existing
  per-card firing — modeling it naively off the per-card event over-fires
  (RULE 603.3f wants exactly one trigger per simultaneous batch, the same
  reasoning MEC-78's `graveyard_exit_batch()`/`CARDS_LEFT_GRAVEYARD`
  already established; this is that event's mirror-image mill-side sibling,
  which doesn't exist yet). Confirmed 8 SOLO, 4 also-blocked
  (`parser_probe.py blocked "put into your graveyard from your library"`).
  Colossal Grave-Reaver, Creeping Chill, Devourer of Memory, Hedge
  Shredder, Narcomoeba, Pedantic Learning, Polluted Cistern // Dim
  Oubliette, Sidisi, Brood Tyrant.
- **PAR-98 · Small verified residue batch #2.** Fourteen independent,
  already-confirmed small fixes surfaced while closing out PAR-79's own
  "can't be blocked this turn" residue — bundled as one batch rather than
  fourteen tickets, same convention as PAR-92:
  - "Activate only/costs `<cost>` less if you control a legendary
    creature" as an activation restriction/cost-reduction condition — 4
    SOLO (Brotherhood Spy, Esquire of the King, Haunt of the Dead Marshes,
    Rivendell).
  - "Becomes a `<N>`/`<M>` creature. It's still a land." manland-animate
    compound with no explicit colour word, a leading "until end of turn"
    word order, and (on one card) a separate-sentence unblockable tail —
    PAR-79's sixth increment's colour/subtype widening already closed
    every same-template card; this is separately-shaped residue — 3 SOLO,
    1 also-blocked (Creeping Tar Pit, Siege of Towers, Woodwraith
    Corrupter; Frostwalk Bastion also-blocked on an unrelated clause).
  - "Whenever you cast a spell that's both `<color>` and `<color>`" — a
    two-colour AND cast-trigger filter; `_CAST_SPELL_TRIGGER_RE`'s
    `types`/`cast_of_color` slots are single-colour only today — 5 SOLO, 1
    also-blocked (Battlegate Mimic, Nightsky Mimic, Riverfall Mimic).
  - Delayed sac/destroy tail-form dispatch reaching an *activated* (not
    triggered) ability preceded by its own unblockable-grant sentence, plus
    a "destroy it **and** `<self>`" two-object compound
    `_DELAYED_SAC_EXILE_TAIL_RE` has no shape for yet — 2 SOLO (Wings of
    Hubris, Goblin Sappers).
  - Alora, Cheerful Scout/Thief's own "if you do" tail names the returned
    creature ("it") a second time, or opens a *fresh* untargeted
    opponent-choice pick — the eighth PAR-79 increment's `previous_or_self`
    capture deliberately doesn't reach a second pronoun reference inside
    the follow-up (see `Done_Backend.md`'s PAR-79 entry) — 2 SOLO (Alora,
    Cheerful Scout; Alora, Cheerful Thief).
  - A targeted "return `<creature>` to its owner's hand. If you do,
    `<effect measuring the returned creature>`." composition — the
    untargeted `previous_or_self`/`ChooseObjectsEffect` baking mechanism
    doesn't apply to a genuine RULE 115 target (gone from the battlefield
    by the time "if you do" would read it) — 2 SOLO (Niambi, Esteemed
    Speaker; Meanders Guide — untargeted antecedent, targeted follow-up,
    needs the identical composition from the other direction). First
    Responder is a *related but distinct* third shape ("**then**", not "if
    you do", plus a magnitude reading the just-returned creature's power)
    confirmed a true singleton — see `singletons.md`.
  - "Another target `<qualifier>` permanent you control" where the
    qualifier is "historic" or "nonland" — `resolve_target_kind` doesn't
    recognize either combined with "another…you control" at all — 2 SOLO
    (Guardians of Koilos, Stockpiling Celebrant).
  - "Except by creatures with haste" as an evasion-exception filter, paired
    with a haste-granting effect — 3 SOLO (Agility Bobblehead, Run for Your
    Life, Speed, Young Avenger).
  - "Whenever you sacrifice a clue[ or food]" trigger condition — entirely
    unrecognized today — 6 SOLO (Astrid Peth, Blu, Mansion Prince, Jenny
    Flint, Lazav, Wearer of Faces, Martha Jones, +1 more).
  - "If a land card was milled this way" as a conditional gate after a
    "mill a card" clause — 4 SOLO (Loafing Giant, Locke, Treasure Hunter,
    Lorehold Excavation, Saprazzan Breaker).
  - "Except by `<same-color>` creatures" / "except by walls" as a
    static/resolve-time evasion-exception filter (colour- or type-scoped
    permitted-blocker set) — 2 SOLO (Dread Charge, Varchild's Crusader).
  - "When the last time counter is removed from this card[, while it's
    exiled]" trigger condition — unrecognized regardless of body — 3 SOLO
    (Alaundo the Seer, Riftmarked Knight, Veiling Oddity).
  - "Whenever a creature you control explores" trigger condition —
    unrecognized regardless of body — 5 SOLO (Lurking Chupacabra, Merfolk
    Cave-Diver, Nicanzil, Current Conductor, +2 more).
  - "At the beginning of combat on your turn, if you've cast a noncreature
    spell this turn" combat-phase trigger condition — 6 SOLO, 6
    also-blocked (Franklin Richards, Ascendant; H.E.R.B.I.E., Lovable
    Robot; Hurkyl, Master Wizard; Lockjaw, Slobbering Teleporter, +2 more).
  - A cost-`{X}`-driven "power `<N>` or less" target filter/count on an
    unblockable ability — the filter threshold itself reading the
    activation's own paid X (Minamo Sightbender), or an X-sized target
    count paired with a fixed power filter (Runed Arch) — 2 SOLO, related
    but not identical shapes; may or may not share one fix.

  > PAR-93…PAR-98's counts (above) are confirmed via `parser_probe.py
  > blocked` at PARSER_VERSION 412, 2026-09-16 — a full batch newer than
  > PAR-80…PAR-92's own 386 checkpoint. Re-run before starting either
  > batch, same standing rule as every other ranked count in this file.

## MEC — Game mechanics

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
