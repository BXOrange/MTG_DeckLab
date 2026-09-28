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

- **ENG-48 · `pay_cost_then` announces no X.** "you may pay {X}. If you do, `<X effect>`" pays
  {X} as 0 and substitutes nothing, so the payoff is always empty: Decree of Justice, Flameblast
  Dragon, Squealing Devil, Taj-Nar Swordsmith, Vigil for the Lost (MODELED, silently zero); Hero
  of Leina Tower, Wildborn Preserver (refused in `_pay_cost_then_general` until this lands — lift
  that guard). Needs an X choice in the `pay_cost_then` prompt (engine + board UI) and `x` on the
  branch effects.
- **ENG-49 · `costs.parse_activation_cost` drops unrecognized cost fragments.** A cost part it
  can't read vanishes, so the ability is claimed cheaper than printed. "Sacrifice X `<things>`" is
  refused in the segmenter (Copper-Leaf Angel, Krav the Unredeemed, Springjack Pasture); build
  the variable-count sacrifice cost, then audit which covered cards carry any other silently
  dropped fragment (make the parser report leftovers and fail the ability closed).
- **ENG-50 · Two red full-cache tests, red since before PAR-120 B1 (`e7143168`).** Mana Drain's
  delayed `add_mana` resolves to 0 (`test_cube_batch_22`); Geistwave's "if you controlled that
  permanent, draw a card" never draws (`test_cube_batch_b3`).

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

  > **Ticket-id note:** `PAR-1` through `PAR-118` are all taken — grep
  > `Done_Backend.md` before reusing one (e.g. `PAR-14` is RULE 603.2's
  > trigger limiter, nothing to do with keywords). `PAR-31…PAR-53` was the
  > long-tail's own reserved block (see `PARSER_LONG_TAIL.md`);
  > `PAR-74…PAR-92` is the 2026-09-15 Commander-legal sweep; `PAR-93…PAR-98`
  > is PAR-79's 2026-09-16 close-out split (its true one-offs went to
  > [singletons.md](singletons.md) instead of a ticket); `PAR-99…PAR-106`
  > and the batch tickets `PAR-107…PAR-114` are the 2026-09-16 **saved-deck
  > coverage sweep** (`backend/scripts/deck_coverage.py` across all 56
  > saved decks, cross-referenced against `commander_tail_report.py` at
  > two cluster thresholds — see each ticket's own citation). `PAR-115…
  > PAR-116` were the 2026-09-16 connective-grammar/slot-grammar pair (14_
  > PARSER_GRAMMAR_DESIGN.md's S4/S5, opened once its S0-S3 prerequisites
  > closed under ENG-34…ENG-37); `PAR-115` closed the same day, landing as
  > one incremental connective (`Done_Backend.md`'s own PAR-62 lesson —
  > "S4 lands in increments, contrary to the ticket's own framing" —
  > applied a second time) rather than the ticket's own "rewrite
  > `parse_effect_body`" framing. `PAR-116` closed after its live audit
  > confirmed that PAR-63 had already removed every concrete cross-module
  > duplication, while `TARGET` is the wrong grammar for statics. `PAR-117`
  > is PAR-115's residue (the referent
  > shapes PAR-115 didn't reach); `PAR-118` was ENG-47's `spell_watchers`
  > retirement, `PAR-119…PAR-125` the composed-head/turn-scoped-trigger
  > program (all closed — `PAR-125` was Spiritualize's own `create_turn_
  > trigger.target_kind` controller-binding fix, closed same-day once the
  > fix turned out to be a general one: `CreateTurnTriggerEffect` now bakes
  > the chosen target into the trigger *condition*
  > [`instance_id_override`] instead of rebinding the whole ability's
  > `source` to it, so "you" in an untargeted effect body stays the
  > spell's controller regardless of who controls the target — see
  > `Done_Backend.md`'s PAR-124 entry). `PAR-126` is MEC-101's own parser
  > follow-up (below); first free id: **`PAR-127`**. A genuinely new engine
  > primitive found along the way still files as its own `MEC-*` ticket —
  > `MEC-102` is MEC-101's own such follow-up; next free id: **`MEC-103`**
  > — only the sweep itself stays out of this file.
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

- **PAR-118 · "Exile a card from your hand with N time counters on it, it gains suspend."** Alaundo the Seer's
  "{T}: draw a card, then exile a card from your hand and put a number of
  time counters on it equal to its mana value. It gains '`<last-time-counter
  trigger>`.' Then remove a time counter from each other card you own in
  exile.", The Eleventh Doctor's "you may exile a card from your hand with a
  number of time counters on it equal to its mana value. If it doesn't have
  suspend, it gains suspend.", and The Wedding of River Song's "…then you
  may exile a nonland card from your hand with … Then target opponent does
  the same. Cards exiled this way that don't have suspend gain suspend." —
  3 SOLO, 0 also-blocked (`parser_probe.py blocked "time counters on it
  equal to its mana value"`). Suspend itself is engine-complete
  (`GameObject.granted_suspend`/`_has_suspend`, `RulesEngine.
  remove_suspend_time_counter`, `SuspendUpkeepEffect`; Delay is the existing
  granted-suspend user) — what is missing is the *hand-to-exile pick*
  (interactive `choose_objects`-style, optional, optionally nonland) that
  stamps `time` counters equal to the card's mana value plus the suspend
  grant, and for Wedding the "target opponent does the same" mirror pass.
  Alaundo additionally needs the quoted trigger granted to the exiled card
  (its own trigger is `LAST_TIME_COUNTER_REMOVED`, which exists) and a
  per-owner "remove a time counter from each other card" sweep.

- **PAR-119 · Composed trigger-head grammar (event × actor × subject × quantity ×
  qualifier) — remaining axes.** `parser_probe.py composition summary` at PARSER_VERSION
  456: about 560 distinct trigger heads still block cards whose body parses alone (mostly
  one-card heads). Built: the cast head (`catalogue/spell_phrase.py`), the object head
  (`catalogue/object_trigger_head.py`: enters / dies / attacks / blocks / leaves, deals
  [combat|noncombat] damage [to …], sacrifices / discards `<object>`, attack batches over
  `ATTACKERS_DECLARED`, "isn't blocked", "while `<state>`", the block relation over `related_ids`),
  the player-event head (`catalogue/player_event_head.py`), and "X and/or whenever Y" splits, over
  `catalogue/characteristic_phrase.py` and `catalogue/trigger_context.py`. Still open: **(a) batch
  quantity** — "N or more X enter / leave / are discarded / are put into a graveyard / deal
  combat damage" (three event-specific `_BATCH_*_TRIGGER_RE` rows exist; the engine fires one event
  per object, so a batch needs simultaneous-event grouping, RULE 603.2c, not just a parser row);
  **(b) attack leftovers** — "attacks with your commander", "~ and another legendary creature",
  "creatures with total power N or greater", "creatures with counters on them" (need a per-attacker
  state filter or a sum over the declaration) and a body reading "that many" off an attack batch
  (a new `attackers_declared` amount kind measuring the head's own filter — Lulu, Amazing Alliance,
  Arthur); **(c) zone origin** — "enters from a graveyard/exile", "is put into a graveyard from
  anywhere/a library" (`from_zone` is stamped on `SPELL_CAST` only; the ENTERS event has thirteen
  hand-written fire sites); **(d) player-event leftovers** — "you discard N or more cards" and other
  per-player batches, "an opponent draws a card except the first N they draw in each of their draw
  steps", "you're dealt damage", proliferate, "taps a land for mana" (no event); **(e) cast
  leftovers** — ordinals ("your first spell during each opponent's turn"), "or copies", "that has
  an adventure". Heads that need a *new event* (exploit, saddle,
  expend, commit a crime, unlock a door/room) are `MEC-*` work, not composition. Contraption-crank
  is deliberately not on this list — see `DEFERRED.md`'s permanent non-goals. **Then
  migrate the legacy rows onto the composed heads** (`_GROUP_SUBJECT_RE`,
  `_GROUP_SUBTYPE_SUBJECT_RE`, `_SELF_OR_GROUP_*`, `_DAMAGE_TRIGGER_RE`,
  `_DAMAGE_RECIPIENT_TRIGGER_RE`, `_BECOMES_TARGET_TRIGGER_RE`, the seven
  `_CAST_SPELL_TRIGGER_*` rows, `_BATCH_ATTACK_TRIGGER_RE`, the `_PLAYER_TRIGGER_CONDITIONS` "you …"
  rows): emit the legacy condition keys from the composed head so the `AbilitySpec`s are identical,
  diff the whole cache, delete the row. Known defect to fix in that migration:
  `_CAST_SPELL_TRIGGER_PLAIN_RE`'s "during an opponent's turn" tail is caster-relative
  (`not_controllers_turn`), while RULE 102.2 and the composed head's `phase_relation` are
  controller-relative. Also open from the "otherwise" fix: Insatiable Appetite / Pippin's Bravery
  ("you may sacrifice a Food. If you do, X. Otherwise, Y" — a *targeted* then-branch with an else,
  which `pay_cost_then` cannot carry) and Lorehold Excavation ("if a land card was milled this way …
  otherwise …" — the milled-card rider row does not take an else). Measure each step with
  `parser_probe.py composition heads --family <f>` and `parser_probe.py diff`, and **execute** a
  sample of the newly claimed cards — the parse verdict alone hid wrong-but-MODELED shapes at v450,
  v455 and v456 (see `PARSER_LONG_TAIL.md`).
- **PAR-120 · Shared count / filter / condition vocabulary — remaining scope.**
  **(b) CDA residue:** a CDA inside a quoted grant or "becomes"
  (Druid Class, Beorn's Hospitality, Chimeric Mass, Svogthos, Seize the Storm,
  Elephant Resurgence, Bonny Pall, The Goblin Sparring Grounds — the general grant path
  doesn't route statics to `pt_cda`; plain created */* tokens now do);
  Angry Mob's turn-split CDA.
  **(c) "`<condition>`, `<effect>` instead":** a general magnitude/
  effect override for targeted or unsupported bodies (Galvanize, Rowan ×2, Scythecat Cub,
  Withering Curse, Jetmir's Fixer, Devour Intellect, Pirate's Landing) — `DealDamageEffect`
  doesn't measure an `effect_amounts` operand, so `{"kind": "if"}` can't carry it yet; and
  "otherwise" after an ordinal gate (Rose Room Treasurer, Zimone). **(d) leaving-counter bodies:**
  a delayed token copy of the dying object (Ochre Jelly), an exiled-as-cost source
  (Lost Isle Calling),
  a destroyed target's counters at resolution (Rite of the Serpent).
  **(e) remaining conditions:** "the first card you draw each turn" (Primitive Etchings, Rowen);
  "if you gained life this turn" bodies (16 SOLO, each blocked by its own effect).
- **PAR-128 · Target/group-grammar slots — residue.** The controller-scope, "another" and
  player-subject slots are in the shared target grammar; still failing on the same axes:
  **group** selectors with "other"/scope ("it deals 1 damage to each other creature",
  "other attacking creatures get +1/+0", "all other creatures get -2/-2", "destroy all creatures
  your opponents control", "each creature with flying your opponents control", "each other player
  sacrifices"); the hand-rolled **graveyard** target grammar ("return another target artifact
  card from your graveyard to your hand" — Junk Diver ×3, Deadwood Treefolk ×2, Gixian
  Puppeteer, Carrion Thrash); **plural multi-target** scope ("tap up to 2 target creatures your
  opponents control", "… divided among any number of target creatures and/or planeswalkers your
  opponents control"); a **quality filter before the scope** ("destroy target creature with flying
  an opponent controls", "… an opponent controls with power 2 or less"); "target creature or
  planeswalker" still collapses to `creature` (a `creature_or_planeswalker_you_dont_control` frame
  would fix both forms); "target opponent `<verb>` for each …" (Honden of Night's Reach, Bishop of
  the Bloodstained). Measure with `parser_probe.py composition mods --axis "control|another|scope"`.
- **PAR-121 · Subject-scope slot and per-verb connective de-duplication (no
  coverage change).** Roughly a third of the parser's regexes sit in
  near-duplicate clusters (`parser_probe`-style token-similarity clustering,
  49 clusters). The two families that matter: **(a) subject scope** — the same
  verb re-registered per subject (self / target / previous target(s) / group /
  attached host / "its controller"): prevent-damage ≈27 rows, skip-untap,
  pump-previous/target/group, its-controller draw/discard, attached
  tap/exile/phase-out; **(b) connectives** — the `_X_THEN_WHEN_YOU_DO_
  RE` family re-matches an antecedent the normal clause parser already handles
  (`_TAP_THEN_WHEN_YOU_DO_RE` hard-codes one card's whole text). Also the 32
  `*_DEVOTION_*` rows, which are verb × one count phrase (fold into PAR-120's
  table). Measured 2026-09-21: only 1 clause fails as a whole when every
  sentence parses, so this is maintainability and future-recombination work —
  do it when touching a verb, and never as a large batch (handler-recipe.md's
  v408 lesson: audit shipped rows, delete strict subsets).
- **PAR-122 · Trigger-doubler residue.** The composed `trigger_doubler` (cause × subject) is
  built; what still fails closed is a *player-event cause* ("turning a face-down permanent face up" — Panoptic Projektor, "a creature you control becoming
  the target of …" — Valiant Emberkin, "being dealt damage" — Wayta; each needs its head in
  PAR-119's player-event axis first), a *compound subject* ("~ or an Equipment attached to it" —
  Cloud, "another colorless permanent or a colorless spell" — Echoes of Eternity, "while you
  control six or more Shrines" — Sanctum of All), The Fish Brewer's tap-for-extra-copies and
  The Masamune's granted quoted doubler.
- **PAR-123 · Group-subject pronoun residue.** The parse stamps a bare "it"/"that
  creature" under a group trigger as the firing object for `tap` / `return_to_hand` /
  `exile` / blink, and the plain "it gets +N/+N [and gains `<keyword>`] until end of turn" /
  "it gains `<keyword>`" pump reads it too (`PumpEffect.trigger_subject`). Still open: the
  amount forms of that pump ("it gets +X/+X where X …", "+1/+0 for each …" — Angelic Exaltation,
  Asari Captain, Shared Animosity, Thoughtweft Imbuer; a `bind` over the trigger subject), "it
  fights …" (Boxing Ring), "it deals damage equal to its power" (Stalking Vengeance, Warstorm
  Surge), `copy_permanent`, and the delayed return in Rienne, Angel of Rebirth ("return it to
  its owner's hand at the beginning of the next end step" — `create_delayed_trigger`'s
  `previous_or_self` capture falls back to the source and `return_specific_to_hand` is
  battlefield-only, so it needs a graveyard-to-hand variant). One wrong claim is known and small:
  Dragon Tempest's "**it** deals X damage" is dealt by the Enchantment, not the entering Dragon
  (visible only through lifelink / deathtouch / protection); the `damage` dealer needs the same
  `trigger_subject` mode. A bare "it" under a `self_or_group` subject stays refused by the
  composed head (Kappa Cannoneer's correct only because "~" is named first). Add each effect
  type as it is exercised, and execute the card, as `test_par123_group_pronoun.py` does.
- **PAR-99 · Khans-of-Tarkir "choose khans or dragons" Siege cycle.** The
  ETB choice itself (`as ~ enters, choose khans or dragons.`) already
  parses — confirmed via `parser_probe.py blocked "as .* enters, choose
  khans or dragons"`: **0 SOLO, 5 also-blocked**. What's unclaimed on all
  5 cards is each mode's own standing consequence text ("khans — at the
  beginning of each of your main phases, add {G}{G}."/"dragons — whenever
  a creature you control with flying enters, you may have it fight target
  creature you don't control.", different per card) — a stored ETB choice
  gating which of two ongoing triggered/static abilities is live for the
  rest of the game, RULE 613.6-adjacent but keyed to a player choice
  rather than a permanent-count threshold. Citadel Siege, Frontier Siege,
  Monastery Siege, Outpost Siege, Palace Siege.
- **PAR-100 · "At the beginning of each player's draw step, that player
  draws an additional card" (+ variants).** An "each player"-scoped draw
  trigger whose effect binds to "that player" (the one whose draw step it
  is) rather than "you" — distinct from the already-shipped "you" forms.
  Confirmed via `parser_probe.py blocked "at the beginning of each
  player.s draw step"`: **10 SOLO, 1 also-blocked** (Mornsong Aria).
  Academy Loremaster, Anvil of Bogardan, Dictate of Kruphix, Font of
  Mythos, Howling Mine, Kami of the Crescent Moon, Nekusar, the Mindrazer,
  Rites of Flourishing, Spiteful Visions, Teferi's Puzzle Box.
- **PAR-102 · Pump + arbitrary keyword/quoted-ability grant in one
  sentence (general form).** "Target/that creature gets +N/+N and gains
  `<keyword>`/"`<quoted ability>`" until end of turn" — PAR-79's own
  widening only covers this combined with *unblockable* specifically;
  every other keyword or quoted-ability tail on the same pump sentence
  stays unrecognized. The single biggest new cluster in this sweep.
  Confirmed via `parser_probe.py blocked "gets \+\[0-9\]/\+\[0-9\] and
  gains"`: **104 SOLO, 34 also-blocked** at PARSER_VERSION 447 — two
  independent axes, split by whether the text after "gains" contains a
  quote:
  - **(a) Plain printed-keyword tail — 86 SOLO, 29 also-blocked.** A
    keyword-list widening (`catalogue/keywords.py`'s word table +
    the existing pump row's tail), the bulk of the cluster — e.g. Enlarge,
    Colossal Growth (its kicker-conditional "instead" override is the
    separate MEC-82 gap noted in CLAUDE.md). None of this ticket's original
    example cards were from this half; all six were from (b).
  - **(b) Quoted-ability tail — 18 SOLO, 5 also-blocked.** Not a
    per-ability row list: for most inner texts the segmenter already claims
    the ability standalone (verified: "when ~ dies, return it to the
    battlefield tapped…", "…and suspect it", "whenever ~ deals combat
    damage to a player, draw a card" all claim; Dreadmaw's Ire's "destroy
    target artifact that player controls" does not), so the fix is the
    shell **recursing into the standard ability grammar** (as
    `_QUOTED_GRANT_RE`/`_ATTACHED_QUOTED_GRANT_RE` already do for static
    grants). Measured by abstracted inner text: 8 of the SOLO cards ride
    one trigger, "when ~ dies, return it to the battlefield…" with a
    rider variant (tapped ×4 — Abnormal Endurance, Perigee Beckoner,
    Return to Action, Supernatural Stamina; plain — Demonic Gifts; +
    treasure — Fake Your Own Death; + suspect — Presumed Dead; "dies or is
    exiled → hand" — Ashnod's Intervention); 3 ride "whenever ~ deals
    combat damage to a player, `<effect>`" (Dreadmaw's Ire, Hunter's
    Prowess, Unnatural Moonrise); Viconia, Disciple of Strength/Violence
    share "spend mana as though it were mana of any color to cast this
    spell". After the recursion lands, re-run `blocked` and route whichever
    inner abilities (Full Steam Ahead, Galuf's Final Act, Greater Stone
    Spirit, Tower Above) still don't parse standalone to `singletons.md`
    if they have no sibling.
- **PAR-103 · "When `<name>` is put into a graveyard from anywhere,
  shuffle it into its owner's library" (plain triggered form).** Distinct
  from PAR-92's already-scoped replacement-effect form ("if `<name>` would
  be put into a graveyard..., reveal `<name>` and shuffle it... instead");
  this is an ordinary RULE 603 trigger with no replacement/reveal. Confirmed
  via `parser_probe.py blocked "is put into a graveyard from anywhere,
  shuffle it into its owner.s library"`: **1 SOLO (Worldspine Wurm), 5
  also-blocked** (Dread, Guile, Purity, Serra Avatar, Vigor — each also
  carries one unrelated second clause of its own).
- **PAR-104 · Teenage Mutant Ninja Turtles "create a mutagen token" set
  mechanic.** A TMNT-specific token type + its ETB/cast-trigger family,
  zero recognition today. Confirmed via `parser_probe.py blocked "create a
  mutagen token"`: **15 SOLO, 2 also-blocked**. April O'Neil Human
  Element, Crustacean Commando, Genghis Frog, Michelangelo Weirdness to
  11, Mona Lisa Ever Adaptable, Mutant Chain Reaction, Ooze Spill, Ray
  Fillet Man Ray.
- **PAR-105 · "You may cast creature spells from the top of your library"
  static permission.** Same shape as PAR-88 (graveyard-zone play
  permission, itself modeled on `game/top_library.py`'s existing
  from-hand-equivalent permission) but for casting creatures specifically
  off the library top — likely a small widening of the same primitive
  rather than a new one. Confirmed via `parser_probe.py blocked "you may
  cast creature spells from the top of your library"`: **5 SOLO, 3
  also-blocked**. Augur of Autumn, Elven Chorus, Garruk's Horde, Ranger
  Class, Summoning Materia.
> **PAR-99…PAR-105's counts were confirmed via `parser_probe.py blocked` at
> PARSER_VERSION 413 (2026-09-16, cross-referenced against the 56 saved
> decks in `backend/scripts/deck_coverage.py`) and re-verified at
> PARSER_VERSION 447 on 2026-09-21 (PAR-100/101/102 corrected above;
> PAR-99/103/104/105 unchanged). Re-run before starting — same standing rule
> as every other ranked count in this file.**

- **PAR-107 · Small residue batch — graveyard/library/exile
  interactions.** 26 independently-shaped clauses (each ≥2 cards
  cache-wide, confirmed via `commander_tail_report.py --min-cluster 2`
  cross-referenced against the 56 saved decks) sharing only a broad theme,
  bundled as one ticket rather than 26 — same convention as PAR-92/PAR-98.
  Work each sub-item independently; a template's own card count is cited
  cache-wide, not deck-only:
  - "When `<name>` is put into a graveyard from anywhere, shuffle it into
    its owner's library." — 6 cache-wide (Dread, Guile, Purity, Serra
    Avatar) — **see PAR-103, already split out.**
  - "You may cast creature spells from the top of your library." — 6
    cache-wide — **see PAR-105, already split out.**
  - "When `<name>` dies or is put into exile from the battlefield, you may
    put it into its owner's library third from the top." (the
    God-Eternal cycle) — 5 cache-wide, **2 SOLO** (God-Eternal Oketra,
    Ilharg, the Raze-Boar), 3 also-blocked (God-Eternal Bontu/Kefnet/
    Rhonas — each by its own second clause: a sacrifice-draw ETB, a
    reveal-first-draw copy trigger, a double-power ETB).
  - "You may cast this card from your graveyard." (plain, no named
    keyword ability) — 3 cache-wide (Hogaak Arisen Necropolis, Skaab
    Ruinator, Their Number Is Legion).
  - "Counter target spell unless its controller pays `<cost>` for each
    card in your graveyard." — 3 cache-wide (Circular Logic,
    Countervailing Winds, Rakshasa's Disdain).
  - "`<cost>`: target player exiles a card from their graveyard." — 3
    cache-wide (Merrow Bonegnawer, Relic of Progenitus, Scrabbling
    Claws).
  - "When `<name>` enters, if an opponent controls more lands than you,
    search your library for a basic Plains card, put it onto the
    battlefield tapped, then shuffle." — 2 cache-wide (Loyal Warhound,
    Scouting Hawk).
  - "Exile target permanent with mana value `<n>` or greater." — 2
    cache-wide (Despark, Kin-Tree Severance).
  - "When `<name>` dies, put it on the bottom of its owner's library." —
    2 cache-wide (Fell Horseman // Deathly Ride, Murderous Rider // Swift
    End).
  - "Reveal the top `<n>` cards of your library. You may put a creature or
    land card from among them into your hand. Put the rest into your
    graveyard." — 2 cache-wide (Grisly Salvage, Scout the Borders).
  - "When `<name>` dies, you may cast it from your graveyard as an
    Adventure until the end of your next turn." — 2 cache-wide (Hildibrand
    Manderville // Gentleman's Rise, Mosswood Dreadknight // Dread
    Whispers).
  - "You may cast this card from your graveyard using its Blitz ability."
    — 2 cache-wide (Sabin Master Monk, Tenacious Underdog).
  - "Return all artifact and enchantment cards from your graveyard to the
    battlefield." — 2 cache-wide (Brilliant Restoration, Redress Fate).
  - "Look at the top `<n>` cards of target player's library, then put them
    back in any order. You may have that player shuffle." — 2 cache-wide
    (Natural Selection, Portent).
  - "When `<name>` enters, if it was kicked, search your library for a
    land card with a basic land type, reveal it, put it into your hand,
    then shuffle." — 2 cache-wide (Sprouting Goblin + its Alchemy
    rebalance).
  - "When `<name>` enters, target creature an opponent controls gets
    -X/-X until end of turn, where X is the number of permanent cards in
    your graveyard." — 2 cache-wide (Chupacabra Echo, Cloud of Darkness).
  - "When `<name>` enters, mill `<n>` cards, then you may return a land
    card from your graveyard to your hand." — 2 cache-wide (Eccentric
    Farmer, Pothole Mole).
  - "When `<name>` enters, exile another target permanent. Return that
    card to the battlefield under its owner's control at the beginning of
    the next end step." — 2 cache-wide (Flickerwisp, Glimmerpoint Stag).
  - "Return target creature card from your graveyard to the battlefield
    with an additional +1/+1 counter on it." — 2 cache-wide: **1 SOLO**
    (Prison Break), 1 also-blocked (A-Graveyard Shift, blocked by its own
    conditional-flash clause). The earlier "Prison Break + its Alchemy
    rebalance" citation was wrong — no `A-Prison Break` is cached; the
    second member is a different card printing the same effect body.
  - "`<cost>`, `<cost>`: exile another target creature. Return that card
    to the battlefield under its owner's control at the beginning of the
    next end step." — 2 cache-wide (Angel of Condemnation, Roon of the
    Hidden Realm).
  - "At the beginning of your end step, if you didn't play a card from
    exile this turn, create a tapped Powerstone token." — 2 cache-wide:
    **1 SOLO** (Visions of Phyrexia), 1 also-blocked (A-Visions of
    Phyrexia — its rebalanced upkeep clause, "exile the top two cards …
    play one of those cards", is a distinct unclaimed variant of the
    original's "top card / that card").
  - "When `<name>` enters, look at the top `<n>` cards of your library.
    You may reveal a creature card from among them and put it into your
    hand. Put the rest on the bottom of your library in any order." — 2
    cache-wide: **1 SOLO** (Growing Rites of Itlimoc // Itlimoc, Cradle of
    the Sun), 1 also-blocked (Foul Emissary, blocked by its own emerge-
    sacrifice trigger).
  - "Exile up to `<n>` target creatures you control, then return those
    cards to the battlefield under their owner's control." — 2 cache-wide
    (Displace, Illusionist's Stratagem).

  > **Atomic-decomposition note — the three "exile `<target(s)>`, return
  > `<it/those>` to the battlefield" bullets above (Flickerwisp's ETB
  > form, the `<cost>`-activated form, Displace's multi-target form) are
  > one axis, not three:** the blink family already exists
  > (`handlers._BLINK_PLAIN_RE`/`_BLINK_NON_SUBTYPE_RE`, `BlinkEffect`, and
  > the RULE 603.7 delayed-return path `ExileEffect(remember=True)` +
  > `ReturnLinkedExileEffect` from PAR-74), and the variation is only (a)
  > the wrapper — ETB trigger vs. activated cost — (b) the target count/
  > filter, and (c) *when* it returns (immediately vs. at the next end
  > step). Check which of those three the existing rows lack before writing
  > any dedicated row.
  - "Search your library for an instant card or a card with flash, reveal
    it, put it into your hand, then shuffle." — 2 cache-wide (Mystical
    Teachings, Waterlogged Teachings // Inundated Archive).
- **PAR-108 · Small residue batch — miscellaneous shapes.** 14
  independently-shaped clauses (excluding the 3 already split out into
  their own tickets above), each ≥2 cards cache-wide:
  - "Destroy target artifact, enchantment, or creature with flying." — 3
    cache-wide (Airship Crash, Broken Wings, Return to the Earth) — a
    three-way OR across different characteristic dimensions: two card
    types plus one keyword-bearing creature filter.
  - "`<name>` deals damage equal to the sacrificed creature's power to any
    target." — 3 cache-wide (Fling, Kazuul's Fury // Kazuul's Cliffs,
    Thud).
  - "Whenever enchanted land is tapped for mana, its controller adds an
    additional `<cost>`." — 2 cache-wide (Overgrowth, Wolfwillow Haven).
  - "Counter target spell, activated ability, or triggered ability." — 2
    cache-wide (Disallow, Voidslime) — generalize `CounterSpellEffect`'s
    target kind beyond "spell" to abilities on the stack.
  - "Whenever N or more other creatures you control with power `<n>` or
    less enter, draw a card. This ability triggers only once each turn."
    — 2 cache-wide: **1 SOLO** (Welcoming Vampire), 1 also-blocked
    (Enduring Innocence — also carries PAR-111's Enduring-cycle dies-return
    clause, so it needs both tickets' handlers).
  - "`<name>` deals `<n>` damage to each non-Dragon creature." — 2
    cache-wide: **1 SOLO** (Breath Weapon), 1 also-blocked (Desolation of
    Smaug, blocked by its own dragon-only restricted-mana clause).
  - "You may have `<name>` enter as a copy of a creature you control,
    except it's a Shapeshifter Rogue in addition to its other types." — 2
    cache-wide (Glasspool Mimic // Glasspool Shore, Visage Bandit).
  - "Target opponent exiles a creature or planeswalker they control with
    the greatest mana value among creatures and planeswalkers they
    control." — 2 cache-wide (Blot Out, End of the Hunt).
  - "At the beginning of your upkeep, if you have `<n>` or more life, you
    win the game." — 2 cache-wide (Felidar Sovereign, Test of Endurance).
  - "At the beginning of your upkeep, you gain X life, where X is the
    number of cards in your hand minus `<n>`." — 2 cache-wide: **1 SOLO**
    (Ivory Tower), 1 also-blocked (The Archimandrite, blocked by its own
    life-gain-triggered pump clause).
  - "As long as you have at least `<n>` life more than your starting life
    total, creatures you control get +`<n>`/+`<n>`." — 2 cache-wide
    (Leyline of Hope, Righteous Valkyrie).
  - "Counter target spell with mana value X." — 2 cache-wide (Spell
    Blast, Spell Burst).
  - "Whenever you tap a creature for mana, add an additional `<cost>`." —
    2 cache-wide (Badgermole Cub, Leyline of Abundance).
  - "Whenever you cast a spell from anywhere other than your hand, draw a
    card." — 2 cache-wide (Vega the Watcher + its Alchemy rebalance).
  - "Look at target player's hand." — 2 cache-wide (Clairvoyance, Peek).
- **PAR-109 · Small residue batch — static/activated abilities &
  mana.** 9 independently-shaped clauses, each ≥2 cards cache-wide:
  - "Equipped creature has `<quoted ability>`" — 6 cards, **not a
    cluster.** The quoted-grant shell (`static_handlers.
    _ATTACHED_QUOTED_GRANT_RE`) already works; the `<name>` in the
    abstracted template hides six different inner abilities, each
    independently unclaimed (same finding as the PAR-82/PAR-106 audit). By
    inner ability, checked cache-wide:
    - **Trigger doubler ("…triggers an additional time"): The Masamune** is
      one of **32** cached cards printing this axis (Panharmonicon, Teysa
      Karlov, Naban, Chief of the Wilds, Cloud Midgar Mercenary, …)
      differing only in the scope filter. The engine primitive exists
      (`continuous.trigger_doubler_bonus`/`TriggerDoublerEffect`, built for
      Roaming Throne) and is used by hand-authored cards only — the parser
      side is **PAR-122**, not a per-card row.
    - **"Conjure a card named `<X>` onto the battlefield tapped and
      attacking":** Stormforged Armor (SOLO) + Kari Zev, Crew of Two (also
      blocked by its own riders) — a 2-card Alchemy-conjure cluster.
    - **No sibling cache-wide → `singletons.md` Batch 3:** Conformer
      Shuriken, Lobe Lobber, Shuriken, Fishing Pole.
  - "[Basic] lands you control have `<quoted mana ability>`" — 4 cache-wide,
    **2 SOLO** (Nexos, Worldknit), 2 also-blocked (Resonating Lute,
    Sovereign's Realm — each by unrelated clauses). Unlike the equipment
    grant this is a **real shell gap**: even the unrestricted
    `Lands you control have "{T}: Add one mana of any color."` is
    unclaimed by the segmenter, so the fix is a land-group
    mana-ability-grant row, not per-card work. A secondary axis is the
    RULE 605.3a spend restriction on the granted ability ("only on costs
    that contain {X}" — Nexos, plus Rosheen, Roaring Prophet's own ability;
    "only to cast instant and sorcery spells" — Resonating Lute).
  - "Untap `<name>` during each other player's untap step." — 4
    cache-wide: **2 SOLO** (Bender's Waterskin, Thousand Moons Infantry),
    2 also-blocked (Endbringer, Victory Chimes — each by its own second
    clause).
  - "`<cost>`: permanents your opponents control lose hexproof and
    indestructible until end of turn." — 3 cache-wide: **1 SOLO**
    (Shadowspear), 2 also-blocked (Luxior and Shadowspear, The Fire Nation
    Drill — each by its own second clause).
  - "You may activate abilities of creatures you control as though those
    creatures had haste." — 3 cache-wide: **2 SOLO** (Shang-Chi, Master of
    Kung Fu; Thousand-Year Elixir), 1 also-blocked (Tyvar, Jubilant
    Brawler).
  - "`<cost>`: target land you control becomes a `<n>`/`<n>` Elemental
    creature with haste until end of turn. It's still a land. Activate
    only as a sorcery." — 2 cache-wide (Llanowar Loamspeaker + its
    Alchemy rebalance).
  - "`<cost>`: `<name>` deals `<n>` damage to each other creature with
    flying." — 2 cache-wide (Harbinger of the Hunt, Scourge of Kher
    Ridges).
  - "`<cost>`: Dragons you control get +`<n>`/+`<n>` until end of turn."
    — 2 cache-wide: **1 SOLO** (Lathliss, Dragon Queen), 1 also-blocked
    (Ran and Shaw, blocked by its own conditional token-copy trigger).
  - "Equipped creature gets +`<n>`/+`<n>` and is every creature type." —
    2 cache-wide (Amorphous Axe, Runed Stalactite).
- **PAR-110 · Small residue batch — board wipes & mass effects.** 7
  independently-shaped clauses, each ≥2 cards cache-wide:
  - "`<name>` deals X damage to each creature." — 2 cache-wide (Savage
    Twister, Starstorm).
  - "Each player exiles all creature cards from their graveyard, then
    sacrifices all creatures they control, then puts all cards they
    exiled this way onto the battlefield." — 2 cache-wide (Living Death,
    Living End).
  - "Each player chooses any number of creatures they control with total
    power `<n>` or less, then sacrifices all other creatures they
    control." — 2 cache-wide (Destined Confrontation, Slaughter the
    Strong).
  - "Put all creatures on the bottom of their owners' libraries." — 2
    cache-wide (Hallowed Burial, Terminus).
  - "Destroy all creatures. You gain `<n>` life for each creature
    destroyed this way." — **1 SOLO** (Fumigate), 1 also-blocked (Avenge,
    blocked by its own unrelated conditional cost reduction).
  - "Destroy all nonartifact creatures." — 2 cache-wide (Organic
    Extinction, Their Name Is Death).
  - "Each opponent sacrifices a creature or planeswalker with the
    greatest mana value among creatures and planeswalkers they control."
    — 2 cache-wide (Flare of Malice, Soul Shatter).
  - "Target player mills half their library, rounded down." — 2
    cache-wide (Cut Your Losses, Traumatize).

  > Check whether `object_filter`/`creature_filter` reaches the
  > mass-destroy/damage clauses before adding dedicated rows.
- **PAR-111 · Small residue batch — ETB/dies/leaves-the-battlefield
  triggers.** 6 independently-shaped clauses (excluding PAR-104, already
  split out), each ≥2 cards cache-wide:
  - "When `<name>` dies, if it was a creature, return it to the
    battlefield under its owner's control. It's an enchantment." (the
    Enduring cycle) — 5 members, only **2 SOLO** (Enduring Curiosity,
    Enduring Tenacity); the other 3 each carry a second, distinct unclaimed
    clause: Enduring Courage (pump-and-haste grant on ETB), Enduring
    Friendship (`double team` + an instant/sorcery-cast anthem), Enduring
    Innocence (the "1 or more other creatures with power `<n>` or less
    enter, draw" trigger — **see PAR-108**, which lists the same card).
  - "When `<name>` enters, manifest dread, then attach `<name>` to that
    creature." — 4 cache-wide (Conductive Machete, Cursed Windbreaker,
    Dissection Tools, Killer's Mask).
  - "Whenever a creature an opponent controls enters, you may have that
    player lose `<n>` life." — 2 cache-wide (Blood Seeker, Suture
    Priest).
  - "Whenever a creature an opponent controls dies, that player loses
    `<n>` life." — 2 cache-wide (Assault Intercessor, Massacre Wurm).
  - "When `<name>` exploits a creature, scry `<n>`, then draw a card." —
    2 cache-wide (Stitched Assistant + its Alchemy rebalance).
  - "When `<name>` enters, destroy target artifact or enchantment an
    opponent controls." — 2 cache-wide (Rambunctious Mutt, Witch
    Enchanter // Witch-Blessed Meadow).
  - "When `<name>` enters, attach it to target legendary creature you
    control." — **1 SOLO** (Mithril Coat), 1 also-blocked (Mjölnir, Storm
    Hammer, blocked by its own unrelated tap/stun-counter attack trigger).
- **PAR-112 · Small residue batch — counters, tokens & CDA formulas.** 5
  independently-shaped clauses, each ≥2 cards cache-wide:
  - "Create X `<n>`/`<n>` white Angel creature tokens with flying." —
    **1 SOLO** (Entreat the Angels), 1 also-blocked (Decree of Justice,
    blocked by its own unrelated cycling trigger).
  - "−`<n>`: target opponent gets an emblem with `<name>`" — **1 SOLO**
    (Ob Nixilis Reignited), 1 also-blocked (Garruk, Apex Predator, blocked
    by its own two other unrelated loyalty abilities). Note the loyalty
    cost prints a Unicode minus (−), not an ASCII hyphen — a
    `parser_probe.py blocked` regex must use `−`.
  - "Whenever you sacrifice a permanent, put a +`<n>`/+`<n>` counter on
    `<name>`." — **1 SOLO** (Juri, Master of the Revue), 1 also-blocked
    (Blood Aspirant, blocked by its own unrelated activated ability).
  - "At the beginning of your end step, if you gained life this turn,
    create a `<n>`/`<n>` white Cat creature token. Then if you have the
    city's blessing, for each token you control that entered this turn,
    create a token that's a copy of it." — 2 cache-wide (Ocelot Pride +
    its Alchemy rebalance).
- **PAR-113 · Small residue batch — combat triggers.** 6
  independently-shaped clauses, each ≥2 cards cache-wide:
  - "Whenever `<name>` deals combat damage to a player, you get that many
    `<cost>`." — **2 SOLO** (Empyreal Voyager, Peema Trailblazer), 1
    also-blocked (Aurora Shifter, blocked by its own unrelated copy
    trigger).
  - "Whenever `<name>` deals combat damage to an opponent, it deals that
    much damage to each other opponent." — **3 SOLO** (Amarant Coral,
    Grenzo's Ruffians, Hydra Omnivore).
  - "Whenever `<name>` enters or attacks, you may put a land card from a
    graveyard onto the battlefield tapped under your control." — **2 SOLO**
    (Soul of Windgrace + its Alchemy rebalance).
  - "Whenever `<name>` attacks, add `<cost>`. Until end of turn, you
    don't lose this mana as steps and phases end." — **2 SOLO**
    (Brazen Collector, Savage Ventmaw).
  - "Whenever `<name>` attacks while you control a creature with power
    `<n>` or greater, `<name>` gets +`<n>`/+`<n>` until end of turn." —
    **2 SOLO** (Nighthowl Pursuer, Ruby, Daring Tracker).
  - "Whenever `<name>` attacks, it gets +`<n>`/+`<n>` until end of turn
    for each other attacking Goblin." — **1 SOLO** (Goblin Piledriver), 1
    also-blocked (Goblin Rabblemaster, blocked by its own unrelated
    "attacks each combat if able" static).
- **PAR-114 · Small residue batch — cost reduction & alternative
  costs.** 4 independently-shaped clauses, each ≥2 cards cache-wide:
  - "This spell costs `<cost>` less to cast, where X is the greatest power
    among creatures you control." — 4 cache-wide (Mitotic Ultimus, Molten
    Monstrosity, The Great Henge, The Skullspore Nexus).
  - "As an additional cost to cast this spell, discard a card or pay
    `<cost>`." — 3 cache-wide (Lightning Axe, Pumpkin Bombardment,
    Titania Rugged Rumbler).
  - "As an additional cost to cast this spell, sacrifice a creature or
    discard a card." — 2 cache-wide (Bone Shards, Minion Missile).
  - "During turns other than yours, spells you cast cost `<cost>` less to
    cast." — 2 cache-wide (Geyser Drake, Naiad of Hidden Coves).

> **PAR-107…PAR-114's card lists and counts come from a one-pass
> `parse_oracle` + `abstract_clause` scan of the full cache (the same
> classification `commander_tail_report.py` uses), cross-referenced
> against `backend/scripts/deck_coverage.py`'s uncovered-card lists for
> all 56 saved decks, 2026-09-16 at PARSER_VERSION 413 — re-run before
> starting a sub-item, same standing rule as every other ranked count in
> this file. Unlike PAR-92/PAR-98's hand-verified small batches, these
> were not individually re-diagnosed with `parser_probe.py card` before
> filing — do that first for whichever sub-item you pick up, since a
> handler's exact shape depends on details (e.g. an intervening "if"
> clause, a self- vs. target-referent) this scan doesn't capture. PAR-107…
> PAR-113 (not PAR-114) were re-measured at PARSER_VERSION 447 on
> 2026-09-21 by exact `abstract_clause` template match — every sub-item
> above now states its SOLO / also-blocked split where the two differ. Two
> traps for whoever re-runs this: a `<name>` in a template like "`X` has
> `<name>`" is a *wrapper* hiding a quoted inner ability (decompose it
> before counting it as a cluster — see PAR-109), and loyalty costs print a
> Unicode minus (−), not an ASCII hyphen.**

- **PAR-126 · "A spell or ability an opponent controls causes you to discard `<X>`" —
  self-subject trigger family.** MEC-101 (closed) built the primitive this whole cluster
  needs — `EventType.DISCARD_CARD`'s new `cause_controller_id` provenance, `binding.core`'s
  `requires_opponent_caused_discard` trigger-condition predicate, and
  `triggers_mixin._collect_discarded_triggers` (the hand-zone-departure scan a self-subject
  discard trigger needs, since `_collect_triggers`'s main loop is battlefield-only) — and hand-
  authored the first card onto it, Pure Intentions (`game/card_catalogue/p/pure_intentions.py`).
  16 SOLO cards remain (`parser_probe.py blocked "causes you to discard"`, minus Pure Intentions
  and the 4 RULE 614 replacement-shaped ones filed separately as MEC-102), needing pure parser
  recognition, not new engine work: **(a)** a bare self-subject "~ is discarded"/"this card is
  discarded" passive-voice verb has *no* recognition at all yet, even uncaused — confirmed via
  `engine_bench.py inspect --text 'When this card is discarded, it deals 3 damage to any
  target.'`, still UNCLAIMED — `_TRIGGER_VERBS` (segmenter.py) has no passive-voice row and its
  self-subject noun list (`_SELF_MULTI_EVENT_RE` et al.) has no "card" option, only "creature/
  artifact/enchantment/land/permanent/equipment"; **(b)** the "a spell or ability an opponent
  controls causes you to discard `<referent>`" wrapper itself is a distinct sentence shape (the
  grammatical subject is the *causing spell*, not the discarded object), not a bare "~ VERB" —
  needs its own dispatch row emitting `{"event": "DISCARD_CARD", "condition": {"subject": "self"
  | "you"}, "requires_opponent_caused_discard": True}`, mirroring `_DAMAGE_TRIGGER_RE`'s own
  bespoke-regex precedent rather than trying to force it through the bare-verb table; **(c)**
  Pure Intentions' own first ability ("…cards this turn, return those cards…") is a
  `create_turn_trigger` composition (RULE 603.7a) that needs generalizing from its one
  hand-authored instance to a parser row. Library of Leng ("if an **effect** causes you to
  discard a card…") and Nephalia Academy (same "an effect" wording) are a **different,
  broader** condition — not opponent-scoped — and don't belong in this cluster.

## MEC — Game mechanics

- **MEC-98 · RULE 121.5 Perpetual effects.** Duskmourn's "perpetually gains/loses `<ability |
  counter | P/T>`" duration survives *every* zone change (unlike every `temp_*` field/
  `GameState.floating_statics` entry this project has, all cleared on a zone change per RULE
  400.7 — `GameObject.reset_as_new_object`) and persists even onto a copy of the object. No
  primitive exists at all (`grep -rn "perpetual" game/` finds only a comment noting the gap,
  `handlers.py`'s own "it perpetually gets +1/+1" note on Alora, Cheerful Scout). Blocks Consumed
  by History ("until end of turn, whenever a nontoken creature dies, it perpetually gains unearth
  {5}.") and every other Duskmourn "perpetually" card. Needs a durable per-object modification
  list `reset_as_new_object` does *not* clear, consulted by the layer engine/keyword union
  alongside printed+intrinsic+granted.

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
