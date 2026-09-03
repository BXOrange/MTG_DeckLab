# Oracle parser: the long tail — strategy & worked examples

The **examples** document of the three-way split (see
[BACKLOG.md](BACKLOG.md) for open tickets, `Done_*.md` for worklogs). Nothing
here is a ticket to close; it is the standing method for the indefinite part
of parser coverage, plus enumerated samples that calibrate how that tail
actually behaves.

Tracked in the backlog as a single standing entry, `PAR-12`.

## Where coverage stands

Measured by `scripts/coverage_report.py` (ledger-backed via
`services/coverage_db.py`), against the full ~35k-card Oracle universe:

**39.3% covered — 13,688 / 34,811 — as of 2026-09-03, PARSER_VERSION 228.**
(215 + a hand-authored batch = PAR-30, **Waterbend (RULE 701.67) residue —
closed**. v215's three parser wins: "Whenever you / an opponent draws
their **second** card each turn, …" (`segmenter._DRAW_CARD_TRIGGER_NTH_RE`
→ the engine's existing `is_nth_draw_this_turn` predicate; ~+35, closes
The Unagi of Kyoshi Island); "[another] target permanent you control" →
the `permanent_you_control` target kind (closes North Pole Patrol); "up to
one **other** target nonland permanent" → a new `_TARGET_ROWS` row (closes
Invasion Submersible's ETB); and the **waterbend {X}** mandatory
additional cost (`{"waterbend": "x"}` + `legal_actions` `has_x`/`max_x`).
Then a hand-authored batch over six new engine primitives closed the
bodies — Crashing Wave, Foggy Swamp Visions, Waterbender's Restoration,
Waterbending Lesson, Water Tribe Rallier, Ruinous Waterbending, Spirit
Water Revival (see `Done_Backend.md`). The one card left, **Secret of
Bloodbending** ("control target opponent during their next combat phase /
turn"), is deferred to **MEC-51 · Control another player's turn** — the
general Mindslaver primitive, a real standalone engine feature. +45 (v215)
+7 (hand-authored), 0 regressed.)
(214 = PAR-30, **Firebending (RULE ~702.189) grants residue — closed**: the
last open sub-bullet of PAR-29's parser trail, the "whenever you waterbend,
earthbend, firebend, or airbend" bending-verb trigger (Avatar Aang, a strict
singleton — hand-authored). Reusable half: `EventType.BENT` +
`RulesEngine.record_bend` + `GameState.bends_this_turn`, fired from all four
bending primitives — `earthbend`, the waterbend additional-cast-cost payment
(RULE 701.67c), airbend (a new `ExileEffect.bend_kind` param — the only
parser-visible change, `_airbend` now emits it), and a second `ATTACKS`
trigger carrying `RecordBendEffect` on every Firebending creature. Plus an
`EffectSpec.condition` key `did_all_bends_this_turn` for the reflexive
"transform" clause. +1 (Avatar Aang, hand-authored), 0 regressed. See
`Done_Backend.md` "Firebending".)
(213 = PAR-30, **Collect Evidence / Forage / Blight activated-body residue
— closed**: the Lorwyn "Champion" cycle's mandatory `behold_exile`
additional cast cost + a "return the exiled card to its owner's hand"
`ReturnLinkedExileEffect(destination=…)` branch; a trigger-subject-sourced
"it deals damage equal to its power to each opponent"; a "tap [up to one]
target creature and put a stun counter on it" handler with RULE 122.1c
stun-counter skip-untap now enforced in `RulesEngine.set_tapped`;
`conditional_flash={"controller_beholds_subtype": …}` (Molten Exhale); an
optional `behold_two_shared_type` additional cost (Celestial Reunion); a
`type_change` ``legendary`` param + `source_has_subtype` condition key
(Tenth District Hero). Plus eight hand-authored / engine cards — Champion
of the Weird / Path, Tenth District Hero, Elven Passage, Incinerator of the
Guilty, Memory Vampire (with a `cast_without_paying` control-transfer fix),
Conspiracy Unraveler (`granted_alt_cast_cost` — a board-wide RULE 118.9 alt
cost the engine's `alt_cost=True` cast path now scans for), Celestial
Reunion. See `Done_Backend.md` "Collect Evidence (RULE 701.59)".)
(212 = PAR-30, RULE 701.10 exchange-control residue — **closed**. The
twelve remaining bespoke singletons, all hand-authored — no parser
recognition needed, each shape appears on exactly one card. New engine
primitives: `TriggeredAbility.controller_from_trigger_event` (a trigger's
chooser can differ from the ability's own controller — Confusion in the
Ranks) + `ExchangeControlEffect(first_target_kind="trigger_subject")`;
`permanent_you_neither_own_nor_control` target kind (Conjured Currency); a
`nonlegendary` filter + `ActivationCost.not_during_combat` (Djinn of
Infinite Deceits); `destroy_auras_if_exchanged` (Gauntlets of Chaos) /
`draw_if_neither_controlled` (Modify Memory) after-effect riders;
`ExchangeLifeTotalsEffect.life_difference_at_most` (Psychic Transfer);
`TripleExchangeEffect` + `capture="target_player"` (Mirror Mirror's
delayed triple swap); `JuxtaposeEffect` / `CulturalExchangeEffect` (two
selection rounds each, both with a documented simplification);
`ExchangeControlSpellEffect` (RULE 701.10i, exchanging a permanent for a
spell still on the stack — Perplexing Chimera's reflexive "you may" pause,
Sudden Substitution's two independent targets) + `RulesEngine.enqueue_
reflexive_trigger` + `ExchangeControlThenCopyTokenEffect` (Arteeoh, Dread
Scavenger). Also fixed a real `Card.as_copy` bug found by execute-testing
Arteeoh: `add_types` naming "creature" never flipped `is_creature`, so a
`set_power`/`set_toughness` override tripped `Card.__init__`'s own
invariant. +12, 0 regressed. See `Done_Backend.md`.)
(211 = PAR-30, RULE 701.10 exchange-control residue — the cross-target
legality predicates. `ExchangeControlEffect` gains resolve-time
`shares_type` ("…that share[s] a card/permanent type with it" — Daring
Thief, Legerdemain, Role Reversal, Shifting Loyalties) and
`second_not_greater` (`"mana_value"` — Puca's Mischief; `"power"` —
Spawnbroker) checks, one more branch on the existing `exchangeable` no-op
gate — no `legal_targets`/client change, the same documented
simplification the different-controllers no-op already is. Parser: an
optional `_EXCHANGE_XTARGET_TAIL` on the two-explicit / multi handlers, a
dedicated Spawnbroker row, new `subgrammars` rows "target nonland
permanent you control" / "another target permanent",
`_EXCHANGE_CONTROL_TARGET_KINDS` widened for the controller-scoped
permanent kinds. +10 (6 exchange cards + 4 "untap another target
permanent" bonus), 0 regressed. See `Done_Backend.md`.)
(210 = PAR-30, Suspect (RULE 701.60) one-off shapes — the four
primitive-blocked singletons the PAR-29 keyword trail left. New
`EffectSpec.condition` key `previous_target_is_suspected` (Agrus Kos,
Spirit of Justice — "if it's suspected, exile it. otherwise, suspect it."
as two complementary condition-gated specs, read off the effect's own
resolved target); `RemoveSuspectedEffect` gains `previous_subject` /
`attached` / `optional` subject shapes (Deadly Complication's "you may
have it become no longer suspected." routed through
`request_choose_objects`, action `"remove_suspected"`); a `subgrammars`
target row for "up to one **other** target creature you control" +
`_batch_attack_group_filter` / `_any_attacking_matches` `is_suspected`
(Clandestine Meddler). Airtight Alibi hand-authored — ETB untap +
hexproof-EOT + un-suspect on the Aura host, plus a static +2/+2 and a
`cant_become_suspected` `grant_keyword` slug `RulesEngine.suspect`
honours (the only card printing that prohibition). +4, 0 regressed. See
`Done_Backend.md`.)
(209 = MEC-50, Clash (RULE 701.30) win/otherwise-branch residue — the six
primitive-blocked singletons the v147–v154 grammar left. `GameContext.
clashed_opponent` is the shared "that player" referent; new
`RepeatProcessEffect` (Hoarder's Greed), `MillEffect` prev-spell-controller
selector (Broken Ambitions), `ReturnToHandEffect` clash-win library
override (Whirlpool Whelm), `GainControlAttachedEffect` (Captivating
Glance), `DiscardEffect.previous_subject` (Pulling Teeth, + the
"whenever ~ deals damage to a player, that player discards" bonus
family), `SkipNextUntapEffect` clashed-opponent scope (Pollen Lullaby).
+34, 0 regressed. See `Done_Backend.md`.)
(208 = Collect Evidence / Forage / Blight residue, sub-cluster (d): "As an additional cost to cast this spell, forage [or pay {M}]." (Feed the Cycle) → `additional_cost={"forage": True}`, the "or pay {M}" alternative dropped as behold/blight already do. +1, 0 regressed. Conspiracy Unraveler still needs a battlefield-granted alternative-cost-for-all-your-spells cast primitive.)
(207 = Collect Evidence / Forage / Blight residue, sub-cluster (b): the
exotic `{cost}, collect evidence N: <body>` / `{T}, Blight N: <body>`
activated abilities. `_COST_LOOKS_REAL` gains the three keyword-action
cost fragments (they never let the line reach the activated handler);
unblocked bodies — "Exile enchanted creature." (`ExileEffect`
``attached_permanent`` mode, + an Aura family), "discard a card. If you
do, `<effect>`" (Gristle Glutton loot), "each opponent loses N life
unless they discard/sacrifice" (`each_player_pay_or` scope + OR cost,
Polygraph Orb). +13, 0 regressed. Hedge Whisperer hand-authored
(`GrantUntilEffect.extra_statics`). See `Done_Backend.md`.)
(206 = Collect Evidence / Forage / Blight residue, sub-cluster (a): the
reflexive *targeted* "When you do, `<payoff>`." after an optional
keyword-action cost (RULE 603.11). A paid `pay_cost_then` now enqueues the
payoff as its own `TriggeredAbility` (`then_trigger` param), so it goes on
the stack with real RULE 115 target selection instead of resolving
off-stack. Generalises far past Collect Evidence — Surgespanner, Teneb,
Bearer of Silence, plus Sample Collector / Curious Forager / Warren
Torchmaster. +43, 0 regressed. See `Done_Backend.md`.)
(205 = Incubate residue closed — the plain "incubate N" cards blocked on
unrelated grammar: reflexive "…unless its controller pays {N}. If they do,
`<effect>`" on a counter + "battle" spell type (Assimilate Essence, Don't
Make a Sound); "if it's a creature, it can't block this turn" damage-rider
gated on the previous target (Searing Barb); "whenever you cast a spell
that targets one or more permanents" cast-trigger filter (Tiller of
Flesh). +4, 0 regressed. Phyrexian Incubator / Progenitor Exarch /
Traumatic Revelation hand-authored — see `Done_Backend.md`.)
(187 = Bucket-A cleanup, Commander-legal tail — `_split_triggered_modal_
block` recognises its trigger wrapper via `segment_line` and carries the
whole trigger dict through, instead of the narrow `_trigger_event`/
`_trigger_condition` pair; a modal block driven by "attacks or blocks",
"whenever you cast a noncreature spell", "at the beginning of your upkeep/
combat", "your second spell each turn", … now parses. +8, 0 regressed —
Elder Gargaroth, Ojutai Exemplars, Etherwrought Page, Cosmogrand Zenith,
Ferocification, Appa. Residue is header-shape work — repeatable-mode
Confluences, "if kicked … instead", "that hasn't been chosen this turn",
haunt/reflexive wrappers — see `BACKLOG.md` "Bucket A residue".)

**Commander-legal slice: ~41.1% — 13,092 / 31,830 (PARSER_VERSION 228).**
This is the subset the product actually plays; `coverage_report.py
--commander-legal-only` measures it and records a separate `<v>-commander`
snapshot row, and `scripts/commander_tail_report.py` (read-only) segments
the ~19k still-UNMODELED Commander-legal cards by *cause* — wrapper
re-measure (A), recurring template → `PAR-*` (B), set-specific → `PAR-*`
(C), missing engine primitive → `MEC-*` (D), bespoke hand-authoring tail →
PAR-12 (E). First wave of derived tickets: `PAR-31…PAR-53`, `MEC-47…MEC-49`
in `BACKLOG.md`. Goal is literal 100% of that slice (minus the RULE 123
sticker non-goal); expect E to stay several thousand one-card entries after
every generalisable cluster is closed.
(109 = PAR-29's RULE 701.60 Suspect designation, +8. 110 = PAR-29's RULE
701.35 Detain designation, +10. 111 = PAR-29's "Blight N" standalone form,
+1 — the cost forms are a separate build, tracked in BACKLOG. 112 = PAR-29's
RULE 701.63 Endure, +7. 113 = PAR-29's RULE 701.70 Recruit, +5. 114 = PAR-29's
"Parser-shaped only" residue batch — Connive targeting/previous-subject/
dynamic-X, standalone double/triple power-and-toughness, general exchange
control/exchange life totals, Populate/Endure "X times"/"endures X" riding
the plain `"x"` sentinel, Bolster/Support dynamic amounts, and a suspected-
creature target filter, +28. 115 = PAR-29's RULE 701.30 Clash — the
`RulesEngine.clash` primitive, `effects.ClashEffect`, the `clash_won`
`ConditionalEffect` key, and `EventType.CLASHED`/`WON_CLASH` — plus "clash
with an opponent" / "if you win …/otherwise …" / "whenever you clash"
handlers, +9. The other ~24 cache clash cards stay UNMODELED on ordinary
effect-grammar residue in their win branches — "return ~ to hand", "those
creatures gain …", "that player …", "repeat this process" — not on clash.
116 = PAR-29's RULE 701.53 "incubate N" — a parser handler only, emitting
the `create_token` + `extra_counters` spec Glissa, Herald of Predation's
hand-authored entry already used (the Incubator DFC token and its "{2}:
Transform" bind off the token name via `ability_catalogue/entries_008.py`),
+13. Dynamic "incubate X, where X is `<count>`" stays open — needs
`create_token`'s `extra_counters` to accept a count-selector/`"x"` sentinel;
"incubate N twice" / "incubate N that many times" likewise.
117 = PAR-29's RULE 701.48 Learn — `RulesEngine.learn` opens an optional
discard-then-draw via the existing `request_choose_objects` chooser
(`optional` + `then_specs`); the "reveal a Lesson from outside the game"
branch is a **documented simplification** (dropped — no sideboard, same as
`ability_catalogue/entries_010.py` for Karn's -2). Bare-word handler,
+15.
118 = PAR-29's RULE 701.59 Collect Evidence — a real new
`ActivationCost.collect_evidence` field (a total-mana-value threshold, the
MV-sum sibling of Escape's `exile_from_graveyard` card count), charged by
`RulesEngine.collect_evidence` (auto-picks highest-MV-first — documented
simplification) wherever a cost is paid: `{cost}, collect evidence N:`
activated abilities, `pay_cost_then` ("you may collect evidence N. if you
do, …"), and a bare "you may collect evidence N". `EventType.
COLLECTED_EVIDENCE` + a "whenever you collect evidence" trigger. +3 — most
of the ~9 remaining SOLO cards block on their *effect bodies* (an exotic
land-animation / edict / class-up activated body, a *targeted* "if you do"
payoff `pay_cost_then` can't resolve off-stack, a "rather than pay the mana
cost" alt-cast), not on the cost primitive.
119 = PAR-29's RULE 701.61 Forage — the same cost-family build as 118:
`ActivationCost.forage` (bool — "exile three graveyard cards or sacrifice
a Food"), `RulesEngine.forage` auto-picking between the two halves (Food
first, documented simplification), `EventType.FORAGED`,
`effects.ForageEffect`, `pay_cost_then` / bare / "whenever you forage"
handlers. +3 (Bushy Bodyguard, Corpseberry Cultivator, Treetop Sentries);
Curious Forager's *targeted* "when you do" payoff and Feed the Cycle's
"forage or pay {B}" alt additional cast cost stay open.
120 = PAR-29's RULE 701.4 Behold — `ActivationCost.behold` + `RulesEngine.
behold` (reveal a matching permanent/hand card, fire `EventType.BEHELD`),
wired into `_pay_additional_cast_cost` as a never-blocking additional cast
cost ("or pay {N}" alt dropped, documented). Also ungated the "as an
additional cost to cast this spell," segmenter wrapper from instants/
sorceries — real creature spells carry additional costs. +9.
121 = PAR-29's RULE 701.68 Blight *cost* forms — `ActivationCost.blight` +
`RulesEngine.blight(interactive=False)` (auto-pick highest-toughness),
activated-cost + `_can/_pay_player_cost` + never-blocking additional-cast-
cost wiring, plus `_PAY_COST_THEN_OR_ELSE_RE` → `PayCostThenEffect.
else_effects` for "you may `<cost>`. if you don't, `<effect>`". Fixed the
silent-drop-of-"Blight N"-from-a-cost-string bug. +8.
122 = PAR-29's RULE 701.66 Earthbend — `RulesEngine.earthbend` parks two
`rest_of_game` floating statics on the target land you control (layer-4
`type_change` to a 0/0 creature still a land, layer-6 `grant_keyword`
haste) then `add_counters` N +1/+1; `effects.EarthbendEffect`. Literal
`earthbend N` only; the "return it tapped on death/exile" reminder clause
is a documented simplification. +9.
123 = PAR-29's RULE 701.65 Airbend — "airbend [up to N] target `<X>`" =
exile it, its owner may cast it from exile for a fixed {2}. Reuses
`ExileEffect.grant_owner_play_permission` (→ `GameState.exile_cast_
condition`) plus a new `owner_play_permission_cost` → `GameState.exile_
cast_cost_override`, a fixed alt cost `GameEngine.effective_cast_cost`
substitutes like Flashback/Escape's graveyard cost. Targeted forms only —
"airbend that creature" (trigger-subject pronoun) and "…creature or spell"
(exile off the stack) stay open. +3.
124 = PAR-29's RULE 701.38 Vote — the APNAP voting subsystem:
`RulesEngine.request_vote`/`_advance_vote`/`resolve_vote_choice`/`_tally_
and_apply_vote` (a `vote` `pending_choice` per living player, the same
sweep shape as `request_all_players_decline_or`), `effects.VoteEffect`,
`GameState._pending_vote`. Two outcome shapes parsed: **majority**
("if `<A>` gets more votes, `<X>`. if `<B>` … or tied, `<Y>`.") and
**per-vote scaling** ("`<body>` for each `<A>` vote"), each outcome body
recursively `parse_effect_body`'d. 2-option only; 3+-option (Council
Guardian), "vote for a permanent/card" (Council's Judgment), a carried
per-player subject across "and" (Capital Punishment — fail-closed), and
untargetable-off-stack outcome bodies all stay open. +5.
125 = PAR-29 residue: "each creature you control gains/gets `<X>` until end
of turn" — the distributive-singular phrasing of the existing "creatures
you control gain …" group grant (`_GROUP` / `_GROUP_SELECTORS`), +1
(Moonveil Dragon).
126 = PAR-29's RULE 701.55 Face a Villainous Choice — `RulesEngine.
request_villainous_choice` (the `request_vote` APNAP sweep minus the
tally, each facing player applies their own pick), `effects.FaceVillainous
ChoiceEffect`, `GameState._pending_villainous`. `handlers._face_villainous
_choice` mini-parses the two options (a "they/that player `<verb>`" clause
retried as "target player `<verb>`" so it binds to `targets=[facing]`; a
bare edict maps to a player-less `sacrifice`). Only cards whose *both*
options parse: +2 (Damocles Base, The Dalek Emperor). The rest — "cast a
spell without paying", "put a permanent from hand", "create a copy of that
card", "exile until …", conditional/previous subjects — are PAR-30. Also
fixed a latent bug: "**you** create a … token **with `<kw>`**" was
mis-tagged `creators="each_player"` (the `who` group captured "you").
127 = PAR-29's RULE 701.56 Time Travel — `RulesEngine.time_travel(player,
times)`, `effects.TimeTravelEffect`, a bare "time travel" handler.
Documented simplification (no per-object add/remove choice): remove one
time counter from each suspended card the player owns (opening the RULE
702.62a free-cast window if it empties), add one to each Vanishing-style
permanent they control. "time travel, then time travel" = two of them.
+3 (All of History All at Once, Time Beetle, Wibbly-wobbly Timey-wimey).
128–132 = the ENG-31/33/32 engine-trail (parametric keyword grants;
villainous/vote option bodies + the reanimator-token exile→copy connector;
Waterbend bodies) — see `Done_Backend.md`.
133 = PAR-30's "incubate X, where X is `<count>`" — `CreateTokenEffect.
extra_counters` gained `count_from_count_selector` (a live `continuous.
count_selector` read — lands you control, and a new
`creature_cards_in_your_graveyard` selector) and `count_from_trigger_event`
("that spell's mana value"); "incubate X twice" = `create_token` `count=2`.
"…where X is its power" / "…that many times" stay UNMODELED. +3 (Glistening
Dawn, Blight Titan, Chrome Host Seedshark).
134 = PAR-30's Earthbend residue: "earthbend X, where X is [twice] the
number of `<count>`" (`EarthbendEffect.amount_from_count_selector` +
`amount_multiplier`) and the "earthbend N, then untap **that land**"
pronoun tail — `earthbend` now announces a land referent to
`_announces_creature_target`, and a new `previous_subject`-only
`_TAP_PREVIOUS_SUBJECT_RE` claims "tap/untap that land|permanent|artifact|
creature", which also caught ~8 unrelated "…target creature. Untap that
creature." cards. "…where X is that creature's power" stays UNMODELED. +12.
135 = PAR-30 — three small grammar widenings: (a) "those creatures" / "each
of those creatures" as the RULE 115 previous-target-group pronoun alongside
"they"; (b) "each creature you control **with a counter on it**" group
selector (Iroh, Dragon of the West — ENG-31 firebending grant over a
group); (c) an optional "during an opponent's turn" qualifier on
`_CAST_SPELL_TRIGGER_PLAIN_RE` → the trigger's `not_controllers_turn` gate
(Fire Nation Occupation + the "flash matters" cluster — Brineborn
Cutthroat, Dream Spoilers, Glen Elendra Pranksters, …). +11. Fire Nation
Cadets ("~ has firebending N as long as there's a lesson card in your
graveyard") still needs a self-keyword-grant static shape + that
condition.)

136 = PAR-30 — the threaten / "it gains haste" restatement tail. (a) a
singular-pronoun previous-subject pump family — "it [also] gets +N/+N [and
gains `<kw>`] until end of turn" / "it [also] gains `<kw>` until end of
turn" (`_PUMP_PREV_SINGULAR_*_RE`, `previous_subject_only`), the singular
sibling of `_PUMP_PREVIOUS_TARGETS_*` ("those creatures"). (b) the
connector-split loop now *propagates* the previous-subject referent through
a clause that itself consumed the pronoun ("untap that creature." → "it
gains haste."), so a threaten card's third-and-later restatement sentence
still resolves. (c) `_GAIN_CONTROL_HASTE_TAIL_RE` also accepts "untap that
permanent" and a ", and" join. +50 — mostly the broad "put a +1/+1 counter
on / deal N damage to / untap target creature. it gains `<kw>` until end of
turn" shape (Snakeskin Veil, Gerrard's Command, Rile, Eutropia the
Twice-Favored, …) plus threaten (Malevolent Whispers) and clash "if you
win, that creature gets …" (Fistful of Force) payoffs. The narrower "it
gains **haste** until end of turn" threaten tail proper (63 SOLO) mostly
still blocks on antecedent widening — `_gain_control_eot` rejecting a
qualified target ("an opponent controls with power 2 or less", "with mana
value ≤ the number of Vampires"), an "if you do," wrapper, or "create a
Blood token" not parsing — left open.

137 = PAR-30 — the "[Then] sacrifice / exile `<it / that creature / that
token / them / those tokens>` at the beginning of [the/your] next end step"
trailing clause, the single biggest RULE 701-trail sub-cluster (~100 SOLO
by substring, ~21 that are genuinely SOLO). One **ungated**
`_DELAYED_SAC_EXILE_TAIL_RE` handler → `create_delayed_trigger` (RULE
603.7, `step="end"`, `scope="any"`, inner `sacrifice_specific` /
`exile_specific`) with a new engine `capture="previous_or_self"`:
`CreateDelayedTriggerEffect.apply` bakes in `context.previous_targets` (the
earlier clause's RULE 115 target) → `created_objects` (RULE 608.2, a
just-made token / reanimated card) → `[self.source]` (a bare self-subject
"sacrifice it" with nothing before it — Brackwater Elemental / Deathknell
Kami). Ungated because the capture no-ops cleanly on an empty referent
chain and a create-token antecedent never sets the segmenter's
`previous_subject` flag. +21 (Tidal Wave, Akoum Stonewaker, Dawn of the
Dead, In Thrall to the Pit's kicked-gated form, Footsteps of the Goryo,
Feral Lightning, Thatcher Revolt, …), 0 regressed — the rest of the ~100
stay blocked on their *own* other clauses (populate / conjure / "tapped
and attacking" / kicked riders).

138 = PAR-30 — threaten-effect antecedent widening. `_gain_control_eot`
gained "`(?:another )?target`", a bare "target artifact" kind, and an
optional "with power N or less/greater" filter (threaded to
`GainControlUntilEndOfTurnEffect.creature_filter` → `TargetSpec`). A new
whole-clause `_GAIN_CONTROL_EOT_PER_OPPONENT_RE` ("for each opponent, gain
control of up to 1 target creature that player controls until end of turn.
untap those creatures. they gain haste until end of turn.") reaches the
`count_selector="opponents"` requirement shape `_goad_per_opponent`
already uses — and `GainControlUntilEndOfTurnEffect.apply` now iterates
*every* chosen target rather than `targets[0]`, so the list a
`count_selector` yields is all taken. +6 (Enthralling Victor, Metallic
Mastery, Mass Mutiny, Molten Primordial, Smelt-Ward Ignus, Wrangle), 0
regressed. Still open in the threaten cluster: the targeted-opponent mass
form ("gain control of all creatures target opponent controls …" —
Broadcast Takeover / Call for Aid), the richer haste clause ("until end of
turn, it gains haste and `<X>`" — Furnace Reins / Loki's Scepter / Flayer
of Loyalties), and after-tails (Goatnap's "if that creature is a Goat",
Awaken the Sleeper's "if it's equipped", Bloody Betrayal's "create a Blood
token" — that last blocked only on Blood tokens not parsing at all).

139 = PAR-30 — the pre-daybound Innistrad **werewolf** day/night check
(RULE 603.4 intervening-if). "At the beginning of each upkeep, if no
spells were cast last turn, transform ~." (front → werewolf) and its
mirror "…if a player cast 2 or more spells last turn, transform ~."
(back → human). Two `parse_effect_body` leading-if handlers
(`_WEREWOLF_NO_SPELLS_CONDITION_RE` / `_WEREWOLF_TWO_SPELLS_CONDITION_RE`)
→ `ConditionalEffect`'s new `no_spells_cast_last_turn` /
`two_or_more_spells_cast_last_turn` keys, each reading
`GameState._last_turn_spell_count` — the previous turn's active player's
final cast count, captured at turn rotation, the exact field
`RulesEngine.apply_day_night_turn_check` (RULE 731.2a/2b) already uses for
the daybound/nightbound successor mechanic; the condition never holds on
turn 1 (`_last_turn_player_id is None`), matching that check's own turn-1
no-op. Whitelisted in `spec._ALLOWED_CONDITION_KEYS`. +27 — the whole DFC
werewolf cycle (Reckless Waif, Kruin Outlaw, Mayor of Avabruck, Mondronen
Shaman, Village Messenger, Call of the Full Moon's Aura form, …), 0
regressed. The legacy "deliberately deferred" negative test in
`test_batch9_conditional_transform_family.py` flipped to a positive one.

140 = PAR-30 — the **O-Ring / Banisher Priest / Fiend Hunter** family,
modern one-sentence templating: "exile `<TARGET>` [an opponent controls]
until ~ leaves the battlefield." (~47 SOLO). The engine halves both
pre-existed — `ExileEffect(remember=True)` stamps `GameObject.
linked_exile_id`, `ReturnLinkedExileEffect` reads it back (MEC-21 /
MEC-30 / Skyclave Apparition) — the gap was purely parser recognition,
and specifically that one clause maps to *two* abilities. `handlers.
_exile_until_leaves` emits the exile spec with a new `until_source_leaves`
param; `segmenter.segment_line`, right after building the primary
triggered `AbilitySpec`, checks for that param and appends a companion
`LEAVES_BATTLEFIELD` → `return_linked_exile` `AbilitySpec` via
`Segment.extra_specs`. Target-kind maps "an opponent controls" onto the
`_you_dont_control` kinds ("target artifact or creature an opponent
controls" → `permanent_you_dont_control`, "…defending player controls"
stays a bare kind). +42 (Banisher Priest, Banishing Light, Cast Out,
Conclave Tribunal, Glass Casket, Fairgrounds Warden, Detention Chariot,
Chained to the Rocks, …), 0 regressed. Verified end-to-end: Banisher
Priest's ETB exiles the opponent's creature and putting the Priest in the
graveyard returns it. Still open: the **old two-sentence** O-Ring
templating (Oblivion Ring itself — "exile another target nonland
permanent." + a separate "When ~ leaves the battlefield, return the
exiled card…"), the multi-event trigger forms ("enters or transforms
into ~" — Brutal Cathar; "enters and at the beginning of your first main
phase" — Crack in Time), and per-card after-tails (Driftgloom Coyote's
"if that creature had power 2 or less…", Food Coma's "create a Food
token").

141 = PAR-30 — a one-word regex widen: `_BECOMES_TARGET_TRIGGER_RE` had
only ever matched "**Whenever** ~ becomes the target of a spell or
ability, …", but the ~19-card Innistrad/Zendikar **Illusion cycle**
(Phantasmal Bear, Frost Walker, Skulking Ghost, Gossamer Phantasm,
Illusionary Servant, Phantom Beast, Skulking Fugitive/Knight, Tar Pit
Warrior, …) prints "**When** ~ becomes the target of a spell or ability,
sacrifice it." — semantically interchangeable here (a self-sacrifice
fires identically off the first event either way). `when(?:ever)?`. The
engine side — `EventType.BECOMES_TARGET` (MEC-19's "targets finalized"
choke point in `RulesEngine.check_ward`) driving a `{"subject": "self"}`
`SacrificeSelfEffect` — was untouched. +21, 0 regressed; verified
end-to-end (Lightning Bolt at a Phantasmal Bear sacrifices it). Still
open: the "sacrifice it **unless you discard a land card**" variant
(Cursed Monstrosity) and the quoted-grant forms (Crystalline Nautilus,
Dismiss into Dream, Boneshard Slasher, Makeshift Mannequin).

142 = PAR-30 — **Earthbend residue, card 1 of 3.** "Earthbend N. **When you
do,** `<effect>`." (Earth Rumble). "earthbend N" is a mandatory keyword
action (no "may"), so RULE 603.3's "when you do" sub-trigger is a certainty
and the two sentences collapse to one plain `[earthbend N, <effect>]`
sequence with no interactive branch — the same certain-antecedent rationale
`_SACRIFICE_THEN_WHEN_YOU_DO_RE` uses. `_EARTHBEND_THEN_WHEN_YOU_DO_RE` in
`segmenter`, narrow enough (before-clause must be exactly `earthbend \d+`)
that it can never claim the genuine optional "you may `<action>`. When you
do, …" family. The `<effect>` half ("up to 1 target creature you control
fights target creature an opponent controls") already parsed via the
connector-split loop — only the literal "When you do," between the two
sentences was blocking. +1, 0 regressed.

143 = PAR-30 — **Earthbend residue, card 2 of 3.** "Whenever a **nonland**
creature you control dies, earthbend X, where X is **that creature's
power**." (Beifong's Bounty Hunters). Two small pieces: (a) `_GROUP_SUBJECT_
RE` gained an optional `nonland` qualifier → `condition["nonland"]` →
`effect_binder._build_group_ok`'s new `want_nonland`, a negated main-type
check against the DIES event's snapshotted `object_types` (RULE 400.7 — the
object is gone by the time the trigger check runs), the same shape
`nontoken` already uses; (b) `_EARTHBEND_THAT_CREATURES_POWER_RE` →
`EarthbendEffect.amount_from_trigger_event="power"`, reading the DIES
event's last-known-power snapshot — which `damage_death_mixin` now stamps on
DIES (`power=obj.power`), mirroring the identical stamp LEAVES_BATTLEFIELD
already carried for `LoseLifeEffect.amount_from_trigger_event`. Deliberately
anchored on the literal "that creature's power" so it only claims the
dying-subject read; "its power" / "that creature's toughness" stay
UNMODELED. +1, 0 regressed; verified end-to-end (a 5/5 dying earthbends the
land by 5; a plain land dying doesn't fire the trigger).

The Earthbend residue cluster's **last card, Earthshape**, is hand-authored
(`ability_catalogue/entries_016.py`, no PARSER_VERSION bump) rather than
parsed: the "power <= **that land's power**" threshold is a read of the
just-earthbent land's power that no general handler warrants building for
one Avatar-set singleton. Two documented simplifications — "that land's
power" is modeled as the literal earthbend amount (3; a freshly-animated
land is 0/0 + three +1/+1 counters = 3/3), carried by
`PumpEffect.creature_filter`'s `max_power`, which this pass also taught to
narrow the `selector`-group branch (not only the targeted one); and "You
gain hexproof until end of turn" is dropped (player-level hexproof is
deliberately unmodeled, same call as Veil of Summer in the Kinnan/M-K
batch). **Earthbend residue is now closed** — its BACKLOG bullet deleted.

144 = PAR-30 — **Airbend residue.** `_AIRBEND_RE` only handled "airbend [up
to N] target creature/nonland permanent"; real Avatar cards print a fuller
qualifier set. Widened to "[up to N / exactly N / any number of] [other /
another] target `<X>` [you control]" → the right source-scoping/-excluding
`ExileEffect` `target_kind` (`creature_you_control` /
`other_creature_you_control` / `nonland_permanent_you_control`). New
`_AIRBEND_TRIGGER_SUBJECT_RE` ("airbend that creature / it") →
`target_kind="trigger_subject"` (MEC-38 — reads the firing event's own
`instance_id`), for **Monk Gyatso**'s "you may airbend that creature" on a
group BECOMES_TARGET trigger. One real engine gap fixed along the way:
`ExileEffect`'s `trigger_subject` branch did the exile but skipped every
post-exile rider (owner-play-permission, free-cast window, import tax) —
extracted into a shared `_post_exile` helper both branches call. +2 SOLO
(Monk Gyatso, Airbender's Reversal); the airbend *clause* also stops
blocking Aang Airbending Master / Aang the Last Airbender / Appa Loyal Sky
Bison / Appa Steadfast Guardian (each still UNMODELED on its *own* other
clauses — experience-counter triggers, lesson-spell triggers, a modal
choose, cast-from-exile — separate PAR-30 items). 0 regressed.

145 = PAR-30 — **Airbend residue, cluster closed.** "airbend up to one
other target creature **or spell**" (Aang, Swift Savior). `_AIRBEND_RE`
gained an `or spell` tail → `target_kind="spell_or_creature"` (the MEC-43
Unsubstantiate targeting union — a `nonland permanent … or spell` shape
fails closed, no real card prints it) + a new `ExileEffect.spell_or_
permanent` flag: a chosen target that is a live spell on the stack is
pulled off it via `RulesEngine.move_spell_off_stack(item, "exile")` (RULE
400.1 — it never resolves) instead of `context.exile`, then the same
`_post_exile` recast-permission riders apply. Mirrors `ReturnToHandEffect`'s
own `spell_or_permanent` (Unsubstantiate's own "still on the stack" bounce).
+1; verified end-to-end (a Lightning Bolt on the stack is exiled off it with
a {2} recast override; the same effect still exiles a battlefield creature).
**The PAR-30 Airbend residue cluster is now closed** — its BACKLOG bullet
deleted.

146 = PAR-30 — the **"Create a token …. It gains haste until end of turn."
tail.** Three small pieces: (a) `segmenter._announces_creature_target` now
returns True for a `create_token`/`copy_permanent`/`become_copy` spec, so
the connector-split loop offers "it" to the next clause;
`PumpEffect.previous_subject` falls back to `GameContext.created_objects`
when `previous_targets` is empty (a create clause has no RULE 115 target).
(b) The connector-split loop seeds its pronoun chain from the caller's
`previous_subject`/`previous_selector` — a two-sentence wrapper
(`_EXILE_THEN_COPY_SENTENCE_RE`, `_with_after_tail`) passes
`previous_subject=True` for a span it knows opens with a referent ("create a
token that's a copy of that card. It gains haste …"), and the *first*
sub-part must inherit it rather than restart from nothing. (c)
`_DELAYED_SAC_EXILE_TAIL_RE` gained a `destroy` verb → a new
`destroy_specific` effect (the destroy sibling of `sacrifice_specific`/
`exile_specific`; goes through `RulesEngine.destroy`, so a shield/
indestructible can still save it — Old Hob, Alleycat Blues' "Destroy it at
the beginning of the next end step"). +9 (Harried Dronesmith, God-Pharaoh's
Gift, Séance, Mordor on the March, Mardu Charm, Mardu Monument, Mogg Cannon,
Rebellion of the Flamekin, Salt Road Skirmish), 0 regressed; verified
end-to-end (Harried Dronesmith's ETB Thopter gains haste via
`created_objects`). Residue not on "it gains haste": Molten Duplication
(needs `{TARGET}` "artifact or creature **you control**" scoping — a shared
macro), Old Hob's *other* ability ("target attacking creature **token**"
filter), Artistic Process (a modal `choose 1 —` option body).

147 = PAR-30 — **Clash (RULE 701.30) win-branch residue, batch 1** of an
ongoing section (~23 cards, each win-branch body its own effect grammar).
Five small pieces: (a) "you clash and win" joins "you win a clash" as a
`WON_CLASH` trigger phrasing (Sylvan Echoes). (b) `_FREE_CAST_FROM_HAND_RE`
accepts "…spell **from your hand** with mana value N or less…" word order,
not only the Expertise-cycle "…with mana value N or less from your hand…"
(Marvo, Deep Operative). (c) `return_self_to_hand` accepts "return **this
card** to its owner's hand" (Ringskipper — a "when ~ dies" clash-win body,
source in the graveyard; scoped to that handler, not the shared
`_SELF_SUBJECT` macro). (d) the connector-split loop treats a bare `clash`
spec as a **referent-transparent interstitial** — it neither targets nor
creates, so "create 2 tokens. clash with an opponent. if you win, **those
creatures** gain deathtouch …" (Gilt-Leaf Ambush) carries its pronoun chain
across the clash sentence instead of having it cleared. (e)
`_PUMP_PREV_SINGULAR_PT_RE` accepts "gets **an additional** +N/+N" (Fistful
of Force). +5 (Sylvan Echoes, Marvo, Ringskipper, Gilt-Leaf Ambush, Fistful
of Force), 0 regressed. Still open in the section — each on a distinct
win-branch body: self-bounce cards blocked on their *first* clause (Titan's
Revenge's "~ deals X damage to any target", Redeem the Lost's "protection
from the color of your choice", Recross the Paths' reveal-until-land);
"that player discards N" (Pulling Teeth), "you gain life equal to that
creature's toughness" (Weed Strangle), "~ deals N damage to that creature's
controller" (Lash Out), "~ deals N damage to each creature blocking it"
(Fire Juggler), "repeat this process" (Hoarder's Greed), "destroy all
enchantments your opponents control" (Spring Cleaning), "untap all Forests
you control" (Woodland Guidance), "gain control of enchanted creature"
(Captivating Glance), "doesn't untap during … next untap step" (Entangling
Trap, Pollen Lullaby), and more.

148 = PAR-30 — **"{X}-scaled damage" handler + Clash batch 2.** The bigger
half is a general win: `_damage_x` claims "~ deals **x** damage to
`<target>`" (digit-free, so it never competes with the `NUMBER`-based
`damage` row) and emits `EffectSpec("damage", {"amount": "x"})` — the `"x"`
sentinel `RulesEngine._substitute_x` already rewrites off the spell/
ability's announced {X} at resolution. No handler for it existed at all.
**+20 classic X-burn cards** (Blaze, Devil's Play, Fanning the Flames,
Volcanic Geyser, Cinder Elemental, Heat Ray, Pain Kami, Goblin Dynamo,
Knollspine Invocation, Latulla, Flameblast Dragon, Arcbound Javelineer,
Ballista Squad, …) **plus Titan's Revenge** (a clash card that was blocked
on its pre-clash "~ deals X damage to any target" clause). Verified
end-to-end: `_substitute_x` sets `amount=4`, a 3/3 dies, a player loses 5
to X=5. Also `_DESTROY_ALL_RE` gained an optional " your opponents control"
scope → new `opponents_enchantments`/`opponents_artifacts` selectors in
`_mass_selector_objects` (a scope on any other noun fails closed) — Spring
Cleaning's clash win-branch. +21 total, 0 regressed.

149 = PAR-30 — **"doesn't untap during its controller's next untap step"**,
another big general family (~95 SOLO) that a clash card (Entangling Trap)
sits inside. New `SkipNextUntapEffect` (`skip_next_untap`) sets
`GameObject.skip_next_untap` — RULE 702.19b's *own* one-time flag, already
consumed and cleared in `GameEngine._step_untap` (built for exert), so no
engine plumbing beyond the effect itself. A pure rider — it taps nothing —
so "Tap X. It doesn't untap …" is the ordinary two-clause `[tap,
skip_next_untap{previous_subject}]` sequence, "it" off `previous_targets`.
Three subject shapes (`target <perm>` / `it`·`that <perm>` prev-subject /
`~` self). **Also a standalone fix:** `_tap`'s allowed target kinds never
included the controller-scoped creature kinds, so "tap target creature **an
opponent controls**" (Chillbringer, Berg Strider, half the tempo family)
didn't parse at all — widened to `creature_you_control` /
`creature_you_dont_control` / `other_creature_you_control`. **+51** — the
whole tap-and-freeze tempo family (Frost Lynx, Frost Titan, Frost Trickster,
Dungeon Geists, Nebelgast Herald, Niblis of Frost, Kor Hookmaster, Kor
Entanglers, Barl's Cage, Chandra's Revolution, Hands of Binding, Blustersquall,
Ojutai's Breath, …) plus Entangling Trap. 0 regressed; verified end-to-end
(the flag survives to the untap step, which skips the creature and clears
it). A stale negative test in `test_mec19_becomes_target_family.py` (Frost
Titan asserted UNMODELED) flipped to positive.

150 = PAR-30 — "gains **protection from the color of your choice** until end
of turn" (RULE 702.16 — Gods Willing / Emerge Unscathed / Feat of
Resistance / **Redeem the Lost** [a clash card], ~27 SOLO). The engine
primitive is Mother of Runes' `GrantProtectionEffect` /
`RulesEngine.grant_protection_choice` (the interactive `grant_protection_
color` pick → `temp_protections`, cleared at cleanup) — only this exact
phrasing's parser recognition was missing. `GrantProtectionEffect` gained
a self (`target_kind=None`, "~ gains …" — Jareth/Cartel Aristocrat) and a
`previous_subject` mode ("put a +1/+1 counter on target creature you
control. **it** gains …" — Feat of Resistance). +17 (the Sejiri Shelter/
Sejiri Steppe/Shelter/Stave Off cycle, Center Soul, Emerge Unscathed,
Blessed Breath, Moonlit Strider, the Master-cycle Thornscape/Stormscape,
…), 0 regressed; verified end-to-end (the color pick lands in
`temp_protections`).

151 = PAR-30 — "**reveal cards from the top of your library until you
reveal a `<type>` card. put that card `<onto the battlefield / into your
hand>` and the rest `<bottom / graveyard / shuffle>`**" (~64 SOLU;
**Recross the Paths** is a clash card). Engine primitive is
`RulesEngine.dig_until` / `effects.DigUntilEffect` — the generalized
cascade dig, predicate + both destinations parameterized — so only the
"reveal until a *type* predicate" recognition was missing. `_REVEAL_UNTIL_
TYPE_RE` + a `_DIG_UNTIL_REST_RES` `re.search` over the many "put all other
cards revealed this way …" / ", then shuffle …" tail spellings (rather
than a row per phrasing). Predicates: a land / basic land / creature /
artifact / enchantment / nonland / nonartifact-nonland card. **Fails
closed** on "onto the battlefield **tapped**" (Clifftop Lookout —
`dig_until` has no tapped-entry mode; a land entering tapped vs untapped is
a real difference). **Documented simplification**: "in any order" → the
engine's only bottoming mode, a *random* order. +9 (Recross the Paths, Atla
Palani, Foster, Evolutionary Leap, Madcap Experiment, Audacious Reshapers,
Spinner of Souls, The Regalia, Vivien Nature's Avenger, Yuna's Whistle),
0 regressed; verified end-to-end (dig past two nonlands, Forest onto the
battlefield, the rest bottomed).

152 = PAR-30 — "**you gain life equal to `<its / that creature's>` `<power /
toughness>`**" (~36 SOLO — Bottle Golems / Angelic Chorus / **Weed
Strangle** [a clash card] / Brightmare / Tribute to Hunger / Consuming
Vapors / …). The creature isn't a RULE 115 target of the gain-life effect
itself, so a new `GainLifeEffect.amount_from_subject` string (`"<who>_
<char>"`) names the object + characteristic. Three gated parser rows, one
per pronoun subject: "its" on a bare-`~` trigger → ``self_*``
(`self_subject_only`); "its" on a group trigger ("a creature you control
enters" — the firing creature) → ``trigger_subject_*``
(`group_subject_only`); "that creature's" after another clause →
``previous_subject_*`` (`previous_subject_only`, RULE 608.2h last-known
info — the creature is usually gone by then). The ungated bare "you gain
life equal to its power" fails closed. +14, 0 regressed; verified
end-to-end (self power → +3; a destroyed creature's last-known toughness →
+5).

153 = PAR-30 — "**~ [also] deals N damage to that creature's controller**"
(~22 SOLO — Consign to the Pit / Blur of Blades / Burn the Impure
[previous-subject: "Destroy target creature. …"] · Battle Strain / Dingus
Staff / Gimli [group/trigger: "Whenever a creature blocks/dies, …"] ·
**Lash Out** [a clash card]). New `DealDamageEffect.recipient_subject`
string (`"<who>_controller"`) — derives the recipient *player* from
`GameContext.previous_targets` (RULE 608.2h last-known controller, since
the creature is usually gone) or the firing event's own
``instance_id``/``controller_id`` payload. No RULE 115 target of its own,
so `target_spec` is `None` and `apply` short-circuits to a direct
`deal_damage(player, …)`. Two gated parser rows (`previous_subject_only` /
`group_subject_only`); "~ **also** deals" handled too (Blooming Blast).
+10, 0 regressed; verified end-to-end (both subject modes hit the right
opponent for the right amount).

154 = PAR-30 — two small clash win-branch bodies; **the general-family
seam in the clash residue is worked out** now. "untap all `<basic land
subtype>` you control" (Woodland Guidance) → a new
`continuous.group_selector_objects` ``lands_you_control_of_type_<x>``
branch (the land sibling of the existing ``creatures_you_control_of_type_
<x>``) + a one-line `_is_valid_tap_selector` whitelist widen. "~ deals N
damage to each creature blocking it" (Fire Juggler, 4 cards) → a new
`DealDamageEffect` ``each_creature_blocking_source`` selector — every
battlefield creature whose `GameObject.blocking` names this ability's own
source (read live, combat still in progress). +2, 0 regressed; verified
end-to-end. The last ~7 clash cards (Hoarder's Greed "repeat this
process", Captivating Glance "gain control of enchanted creature", Broken
Ambitions "that spell's controller mills 4", Whirlpool Whelm "put that
creature on top of its owner's library instead", Pulling Teeth /
Pollen Lullaby "that player" cross-branch referent) are genuine singletons
— hand-author candidates, no shared grammar left.

155 = PAR-30 — the Kicker-shaped **optional additional cast cost**
primitive (RULE 601.2b), the `<who>`-flag half of the Waterbend residue's
biggest cohesive cluster. "as an additional cost to cast this spell, **you
may** `<waterbend {N}/blight N/behold X/sacrifice …>`." →
`AbilitySpec.additional_cost_optional`, a second `pay_additional` cast
variant `game/engine/legal_actions_mixin._offer_cast` offers alongside the
plain one (the same "alongside, never in place of" shape as evoke/
help_pay), with `GameObject.additional_cost_paid` recording whether it was
taken. "**if this spell's additional cost was paid**, `<effect>`." →
`EffectSpec.condition`'s new ``"additional_cost_paid"`` key
(`ConditionalEffect`, the generic sibling of ``"bargained"`` — additive
"if paid, extra effect" only; the "…, `<effect>` instead" override shape
stays unclaimed). Threaded `pay_additional` through `can_cast` /
`effective_cast_cost` / `cast_spell` / `_cast_current_face` /
`_auto_tap_for_cast_if_needed` / `_pay_additional_cast_cost` /
`GameSession._dispatch_cast_spell`. +1 (Requiting Hex); the per-card bodies
(Ruinous Waterbending, Spirit Water Revival, Katara Seeking Revenge) were
each their own effect-body grammar — all since closed (Katara v158, the
rest in the v215 hand-authored batch); Secret of Bloodbending deferred to
MEC-51. 0 regressed.

156 = PAR-30 — "**as long as there's a `<subtype>` card in your
graveyard**" (the Avatar: TLA "Lesson" cards), a `static_conditions.py`
`active_if` gate that crossed the Waterbend/Firebend residue. New
`subtype_in_graveyard` kind (a live type-line scan of the controller's
graveyard, `+ subtype + min`; `_STATIC_CONDITION_RES` row) plus its
trigger intervening-if sibling "**if there's a `<subtype>` card in your
graveyard, `<effect>`**" → `ConditionalEffect`'s already-built (but never
parser-wired) `graveyard_has_type` key
(`segmenter._GRAVEYARD_HAS_SUBTYPE_CONDITION_RE`). +6 — Aang A Lot to
Learn, First-Time Flyer, Platypus-Bear, Walltop Sentries (Lesson), plus
Murasa Behemoth ("land card in your graveyard") and Dawnhand Eulogist
("Elf card in your graveyard"). Fire Nation Cadets still blocked on the
"~ has firebending N" self parametric-keyword grant. 0 regressed.

157 = PAR-30 — the **self** parametric-keyword grant static ("~ has
firebending N [as long as `<cond>`]", Fire Nation Cadets), closing the
last lesson-card residue card. ENG-31 shipped the group/pump/token
parametric grants but not the self one; `static_handlers._SELF_GRANT_RE`'s
keyword capture widened to accept a trailing digit and routed through
`_split_keywords_with_parametric` — but only when `_flag_keywords` fails
first, so the ordinary landwalk/flag self-grant path is byte-identical.
Emits `grant_keyword {affects: "self", parametric_keywords: [...]}`, which
`continuous._apply_layer_6_ability`'s existing ENG-31 branch already
applies (and re-synthesizes firebending's ATTACKS add-{R}×N mana ability
off). +1, 0 regressed.

158 = PAR-30 — Katara, Seeking Revenge's two remaining clauses, both
riding primitives from the last three versions. "**~ gets +P/+T for each
`<subtype>` card in your graveyard**" → a self `anthem` scaled by
`continuous.count_selector`'s new `<subtype>_cards_in_your_graveyard`
prefix (a live type-line scan, the sibling of v156's
`subtype_in_graveyard`); the explicit `creature_cards_in_your_graveyard`
row stays its own `Card.is_creature` check. "**`<effect>` unless `<its>`
additional cost was paid**" → the negative, *suffix* form of v155's
`additional_cost_paid` `EffectSpec.condition`, checked *after* the
connector split so it binds to only its own clause ("draw a card, then
discard a card unless her additional cost was paid" → the draw stays
unconditional). +7 — Katara plus every "gets +X/+X for each `<type>` card
in your graveyard" beater the count-selector unlocked (Knight of the
Reliquary, Fiend Artisan, Liliana's Elite, Salvage Slasher, Wight of the
Reliquary, Madame Hydra Reanimated). 0 regressed.

159 = PAR-30 — the "**`<consequence>` unless you pay `<cost>`**" family
(62 cards / 56 SOLO cache-wide). (a) `_UNLESS_COST` — the closed cost
vocabulary `_SACRIFICE_UNLESS_PAY_RE` / `_DESTROY_UNLESS_PAY_RE` share —
gains "discard N cards" (a plain count `parse_activation_cost` /
`_pay_player_cost` already honour); "discard a `<type>` card" (silently
free) and "at random" stay excluded. (b) New `_TAP_UNLESS_PAY_RE` /
`_EXILE_UNLESS_PAY_RE` — the tap/exile consequence siblings — modeled with
no new effect at all: `pay_cost_then` with an empty pay-branch and the
tap/exile spec in `else_effects` (paying costs the resource, declining
taps/exiles the source). Registered before `tap_self`/`exile_self` so the
"unless" half isn't dropped. +8 — Carnophage, Sangrophage, Heavyweight
Demolisher, Electrozoa, Apocalypse Demon, Demonlord of Ashmouth,
Morgul-Knife Wound (granted form), Avatar of Discord. 0 regressed. Still
open in this family: the "discard N cards **unless you discard a `<type>`
card**" body (Alpharael) and follow-up "if ~ is destroyed this way …"
clauses (Cosmic Horror).

160 = PAR-30 — Incubate dynamic amount "…where X is **its power**"
(`_INCUBATE_X_RE` / `_incubate_x`). A "when ~ dies" trigger; the dying
creature's own last-known power is already snapshotted on the DIES event
(`damage_death_mixin`, RULE 400.7), so no engine change — reuses
`CreateTokenEffect.extra_counters`' existing `count_from_trigger_event`
key, the same firing-event idiom `EarthbendEffect` uses for "earthbend X,
where X is that creature's power" (v143). +2 — Bloated Processor, Furnace
Gremlin. 0 regressed. Still open in the Incubate residue: "incubate N
**that many times**" (Phyrexian Incubator — a search-count repeat),
"where X is its **mana value**" of a just-exiled permanent read by *its
controller* (Excise the Imperfect), "X is the number of creatures
**exiled this way**" (Sunfall) — each a distinct unbuilt primitive.

161 = PAR-30 — the shared `TARGET` macro (`catalogue/subgrammars.py`
`_TARGET_ROWS`) gains a **"another target creature you control"** row
(RULE 109.5 — the ability's own source is excluded). The engine's
`other_creature_you_control` kind (`targeting.py`) already did the
exclusion, the "you control" scoping and its German label; the row just
routes the printed phrase there, and `_pump_target` adds the kind to its
pumpable-kind allowlist. Reaches every `TARGET`-embedding handler (pump,
damage, counters, …), not just the pump family that motivated it. +31 —
mostly ETB / combat-trigger creatures granting a keyword until end of
turn (Heavenly Qilin, Duke Ulder Ravengard, Selfless Savior, Void
Grafter, Blooming Stinger, …). 0 regressed. The no-"you control" form
("another target creature" — Arwen, Mortal Queen) stays UNMODELED: its
`other_creature` kind is not engine-wired.

162 = PAR-30 — the Incubate **dynamic-amount** residue, finished. Two
shapes: (a) "Its controller incubates X, where X is **its mana value**"
(Excise the Imperfect) — `CreateTokenEffect.creators` gained
`"previous_target_controller"` (creator = whoever last controlled the
just-exiled `previous_targets[0]`, RULE 608.2h) and `extra_counters` a
`count_from_subject` reading a `"<who>_<char>"` string through a new
shared `_characteristic_of_subject` helper (factored out of
`GainLifeEffect._from_subject`, `char` now covers `mana_value`); the
plain `_exile` handler also learned the real `nonland_permanent` kind
(bonus: Anguished Unmaking, Utter End). (b) "…where X is the number of
creatures **exiled this way**" (Sunfall) — new
`GameContext.objects_exiled_this_way` accumulator, the exact sibling of
`permanents_destroyed_this_way`, bumped by `context.exile` and read via
`extra_counters`' new `count_from_context` key. +4, 0 regressed. Still
UNMODELED (each its own primitive, not dynamic-amount grammar):
"incubate N that many times" (Phyrexian Incubator — a search-result
count across a `pending_choice` suspension) and "incubate N X times"
reading a source's `x_paid` (Progenitor Exarch).

163 = PAR-30 (Vote residue, one point per loop) — self-excluding mass
destroy. New `all_other_creatures` / `other_creatures_you_control`
selectors (`effects._mass_selector_objects`, RULE 400's "other");
`_DESTROY_ALL_OTHER_RE` claims "destroy all other creatures[ you
control]" / "…all creatures other than ~" / "…except [for] ~" + an
optional "can't be regenerated" tail. +1 (Novablast Wurm); also closes
the "destroy all creatures other than ~" branch of Magister of Worth's
vote body (card still blocked on its other branch).

204 = PAR-30 (Threaten / O-Ring trailing items, bullet fully closed) — the
last two singletons. **Call for Aid**: the two anti-abuse riders on the
mass gain-control body — "you can't sacrifice those creatures this turn"
(`GainControlUntilEndOfTurnEffect.mark_no_sacrifice` → `GameObject.cant_be_
sacrificed_this_turn`, checked at every sacrifice candidate site, cleared
at cleanup) and "you can't attack that player this turn" (new
`PreventAttackingPlayerThisTurnEffect` → `GameState.no_attack_pairs_this_
turn`, enforced in `GameEngine._can_attack` against the assigned defender).
**Shackles of Treachery**: `_DAMAGE_TRIGGER_RE` now accepts a bare "deals
damage" (whole "to <recipient>" clause optional; empty filter = any damage
instance), plus a new `equipment_attached_to_source` target kind +
`_destroy_equipment_attached_to_it` handler for the granted quoted
trigger's "destroy target Equipment attached to it". +2.

203 = PAR-30 (Threaten / O-Ring trailing items) — three of the five. **"When
you cast this spell, `<effect>`."** (RULE 601.2i) —
`_CAST_THIS_SPELL_TRIGGER_RE` → `trigger={"event": "SPELL_CAST",
"condition": {"subject": "self"}}`, body `self_subject`; the engine side
was already MEC-43 (`_collect_self_cast_triggers` +
`TriggeredAbility.functions_from_stack`). +15 (Flayer of Loyalties, the
Emerge/Emrakul-brood cycle, Artisan of Kozilek, Decimator of the
Provinces, World Breaker, Desolation Twin …). **"enters or transforms into
~"** (Brutal Cathar) — new `EventType.TRANSFORMED` fired by
`RulesEngine.transform_permanent` after the flip + rebind;
`_SELF_MULTI_EVENT_RE` accepts "transforms into ~" as a verb slot → the
existing event-list shape. +5 (Huntmaster of the Fells, Ulrich of the
Krallenhorde, Ashling Rekindled, Brigid Clachan's Heart). **"when ~ enters
and at the beginning of your first main phase"** (Crack in Time) —
`_ENTERS_AND_MAIN_PHASE_RE` → self `ENTERS_BATTLEFIELD` + controller-scoped
`STEP_BEGIN` (`{"step":"main1"}`, `phase_relation="you"`) + O-Ring
LEAVES_BATTLEFIELD return. +1.

202 = PAR-30 (Threaten / O-Ring residue, closed) — the *old two-sentence*
Oblivion Ring templating: `_return_exiled_card` claims a standalone
"return the exiled card[s] to the battlefield under its/their owner's
control." LTB line (→ `return_linked_exile`), `_exile` gains an "exile
**another** target `<X>`" ETB row, and `gate.parse_oracle` stamps
`remember=True` onto every plain `exile` effect on any card that also
carries a `return_linked_exile` (so `linked_exile_id` is populated).
+10 — Oblivion Ring itself, Journey to Nowhere, Faceless Butcher, Fiend
Hunter, Petravark, Petradon, Slithery Stalker, The Princess Takes Flight,
Eldrazi Displacer, Driftgloom Coyote (its "if that creature had power N
or less, put a +1/+1 counter on ~" after-tail via the new
`previous_target_power_at_most` `ConditionalEffect` key).

201 = PAR-30 (Threaten residue) — the two card-specific conditional
after-tails on a threaten clause: "if that creature is a `<subtype>`, it
also gets +N/+M until end of turn" (Goatnap) and "if it's equipped, you
may destroy all Equipment attached to that creature" (Awaken the
Sleeper), each a `ConditionalEffect` on new `previous_target_*` keys
(`_has_subtype` / `_is_equipped`) reading `GameContext.previous_targets`;
the destroy runs over a new `equipment_attached_to_previous` mass
selector (the "you may" isn't an interactive choice — documented
simplification). +2 (+ Kaseto Orochi Archmage bycatch).

200 = PAR-30 (Threaten residue) — leading "until end of turn, it …"
rich restatements: "it gains haste and '`<quoted ability>`'" (Furnace
Reins — `grant_until(previous_subject=True)` over
`_quoted_ability_grant_effects`), "it becomes a `<subtype>` in addition
to its other types and gains haste" (Loki's Scepter — `type_change`
add-subtype), "it has base power and toughness N/N and gains `<kws>`"
(`pt_set` + residual `pump`); `_DAMAGE_TRIGGER_RE` also accepts "…to a
player or battle" (RULE 310). Plus the opponent-scoped mass threaten
(`_GAIN_CONTROL_MASS_EOT_RE`): `selector="opponents_artifacts"`
(Broadcast Takeover — the mass path now passes `source` to
`_mass_selector_objects`) or `GainControlUntilEndOfTurnEffect.
mass_of_target_player` (one RULE 115 opponent target, then all their
creatures/artifacts). +5 (incl. Beamtown Beatstick / Archpriest of
Shadows bycatch).

199 = PAR-30 (Threaten residue) — `_GAIN_CONTROL_HASTE_TAIL_RE`'s
restatement tail now recurses whatever the "it/they gains … haste …
until end of turn" sentence says beyond bare haste through
`parse_effect_body(previous_subject=True)`, so the shipped
`pump(previous_subject=True)` claims "untap it. it gains trample and
haste until end of turn" (Traitorous Blood) / "…haste and myriad…"
(Firbolg Flutist) with no second RULE 115 target. +2.

198 = PAR-30 "create a token that's a copy of `<named card>`" body
singletons — **Sin, Spira's Punishment**. New self-contained
`RandomGraveyardExileCopyLoopEffect` / `random_graveyard_exile_copy_loop`
— "exile a permanent card from your graveyard at random, then create a
tapped token that's a copy of that card. if the exiled card is a land
card, repeat this process." (RULE 706 `RulesEngine.random_choice` over
the graveyard's permanent cards + RULE 707.2 `create_token` off the
exiled card, looped while each exiled card is a land; `MAX_ITER` hard
stop). The "enters or attacks" trigger already parsed
(`_SELF_MULTI_EVENT_RE`). +1.

197 = PAR-30 "create a token that's a copy of `<named card>`" body
singletons — **Living Laser**. New `GameState.cards_discarded_this_turn`
(bumped at every `DISCARD_CARD` fire site via `RulesEngine.
_note_discarded` — the plain `discard`, `discard_specific`, and the Pitch
additional-cost discard; reset for the incoming active player in
`begin_turn`, exactly like `cards_drawn_this_turn`) +
`continuous.count_selector("cards_discarded_this_turn")` +
`CopyPermanentEffect.count_selector` (overrides `count`, resolved off
live state at `apply`). `_COPY_SELF_FOR_EACH_RE` handler: "for each card
you've discarded this turn, create a token that's a copy of ~[, except
the token isn't legendary]" → `copy_permanent` with `target_kind=None` /
`referent="source"` + the selector. The trailing "the tokens enter
tapped and attacking" (`_CREATED_ENTERS_ATTACKING_RE`) and "exile the
tokens at the beginning of the next end step" (`_DELAYED_SAC_EXILE_TAIL_
RE`) already parsed. The `cards_discarded_this_turn` selector also opens
Change of Fortune / Astonishing Spider-Man territory (still blocked on
their own "when you do" reflexive shapes). +1.

196 = PAR-30 "create a token that's a copy of `<named card>`" body
singletons — **The Vast Scrier**. `request_search` /
`PutFromHandOntoBattlefieldEffect` gain `then_specs_if_none`: "if you
don't put a card onto the battlefield this way, `<body>`." (`scry 2`)
runs `<body>` when the from-hand pick places nothing — declined in
`resolve_search_choice`, or nothing eligible in `request_search` (both
paths carry the serialized specs + a `then_source_id` on the search
`pending_choice`). `_PUT_FROM_HAND_RE` also consumes the reminder
sentence "if it has any 'whenever ~ attacks' triggers, those trigger"
as a no-op — `put_onto_battlefield_attacking` already re-fires ATTACKS
for the placed creature. +1.

195 = PAR-30 "create a token that's a copy of `<named card>`" body
singletons — **The Joiner of Cats**. New `create_token_copy_of_named` spec
/ `CreateNamedCardTokenEffect`: the token's copiable values come from a
real card resolved by name from the cache (`services.card_lookup.
card_by_name` — a `game/`-safe singleton, deliberately *not* in
`card_database.py` whose bytes are hashed into the cache schema
fingerprint). `_CREATE_NAMED_CARD_TOKEN_RE` + `_NAMED_CARD_SHAPE_RE` only
fire on a proper-noun name (" of "/","/"'"/word-internal hyphen), never
"enchanted creature"/"chosen permanent". Plus `impulsive_look` gains
`miss_effect_specs` — the `_LOOK_TOP_PUT_ATTACKING_RE` "if you don't put a
card onto the battlefield this way, `<body>`." else-branch, run in
`resolve_impulsive_look_choice` (declined) / `request_impulsive_look`
(nothing eligible) via `_apply_effect_specs`, source kept off
`state.pending_choice` on `_pending_impulsive_look` (same split
`_pending_name_card` uses). +1.

194 = `normalize` folds a comma-less legendary's **given name** — the
single word before " of " in "Kaalia of the Vast" → `~` — where it's a
genuine self-reference. `_fold_given_name_prefix` is context-gated
(`_PREFIX_TYPE_BEFORE`/`_PREFIX_TYPE_AFTER`) so a name that also reads as a
creature type or keyword keeps that meaning: "another **Cleric** you
control" (tribal filter), "a … **Knight** creature token" (token subtype),
"gains **fear** until end of turn" (keyword) all stay unfolded. Only a
single-word pre-" of " span folds, so "Ghost Council of Orzhova" is
untouched. +5 (Kaalia of the Vast, Karlov of the Ghost Council, Beregond
of the Guard, Braulios of Pheres Band, Sorin of House Markov).

193 = PAR-30 "Tapped and attacking" trail — closes the **Winota, Joiner of
Forces / A-Winota** family and the RULE 508.3a batch-attack trigger. Two
pieces: (a) the `look_top` "…onto the battlefield tapped and attacking."
mid-clause **"It gains <keyword> until end of turn."** interpose —
`_LOOK_TOP_PUT_ATTACKING_RE` grew an optional group validated against
`_LOOK_TOP_HIT_GRANT_KEYWORDS` (fail-closed), threaded as
`hit_grant_keywords` through `impulsive_look` → `ImpulsiveLookEffect` →
`request_impulsive_look` → `resolve_impulsive_look_choice`, which adds
`temp_keywords` to the placed card (RULE 514.2). (b) "whenever **one or
more** [<filter>] creatures you control attack[ a player], …" →
`_BATCH_ATTACK_TRIGGER_RE` maps onto the existing once-per-combat
`EventType.PLAYER_ATTACKED` aggregate with an optional `group_filter`
(`_batch_attack_group_filter`: bare, a negated creature subtype, or a
main type — "modified"/"suspected" fail closed) that
`effect_binder._any_attacking_matches` checks against the live attacking
group; plus a negated-creature-subtype ("non-Human") option on
`_GROUP_SUBJECT_RE` → `_build_group_ok`'s new `excluded_subtypes`. +4
(Winota, A-Winota, Dollmaker's Shop, Requiem Angel).

192 = PAR-30 "Tapped and attacking" trail — the qualified attack trigger
"whenever ~ attacks **a player who controls N or more lands**" (Owlbear
Cub). New `_ATTACKS_DEFENDER_LANDS_RE` keeps it a `{"subject": "self"}`
ATTACKS trigger carrying a `defender_controls_lands_at_least` key, gated
in `effect_binder._trigger_condition` off the ATTACKS event's
`defending_player_id` (the same "gate an ordinary event on a live state
read rather than a state-trigger subsystem" idiom as `controls_none_of_
type`). +1.

191 = PAR-30 "Tapped and attacking" trail — `_DELAYED_SAC_EXILE_TAIL_RE`
gained a **"return `<it / that creature>` to (your | its owner's) hand"**
verb alongside sacrifice/exile/destroy → `create_delayed_trigger` with a
new `return_specific_to_hand` inner (`ReturnSpecificToHandEffect`, the
same `.objects` bake-in via `capture="previous_or_self"` the sacrifice
sibling uses). A loan bounced end of turn / at end of combat — broader
than the tapped-and-attacking seam it was found on: +8 (Alora, Merry
Thief; the "when ~ attacks or blocks, return it … at end of combat"
Phantom Whelp / Windscouter / Quicksilver Behemoth / Wall of Junk cycle;
The Locust God; Dragon Mask), 0 regressed. Ilharg and Zara stay blocked
on their own other clauses.

190 = PAR-30 "Tapped and attacking" — put-from-hand card filters.
"with lesser power" (Shadowfax, Lord of Horses) →
`PutFromHandOntoBattlefieldEffect.power_less_than_source`, a `max_power`
cap vs the effect's source computed at `apply` time (no source power →
`max_power = -1`, fail closed). "with mana value X or less … where X is
the number of attacking creatures you control" (Kinscaer Sentry) →
`max_mana_value_selector`, folded into `criteria["max_mana_value"]` via
`continuous.count_selector` at `apply`; the bare "mana value X or less"
with no "where X is …" fails closed. Fixed "mana value N or less" also
accepted. +2 (Shadowfax, Kinscaer Sentry), 0 regressed.

189 = PAR-30 "Tapped and attacking" — `_CREATED_ENTERS_ATTACKING_RE`
gained two more "before" shapes. (1) A **bare token-name** subject:
"create Ragavan, …. **Ragavan** enters tapped and attacking." (Kari Zev)
— the name only binds a spec whose ``token_name`` matches it, so a
non-matching name fails closed. (2) A **`populate`** before: "populate.
**That token** enters tapped and attacking." (Ghired, Conclave Exile) —
`PopulateEffect` gained ``tapped``/``attacking``, threaded to
`RulesEngine.populate(enter_state=…)` and applied to the copy in the
degenerate 0/1-token paths, carried on the `pending_choice` for the
interactive 2+-token one. +2 (Kari Zev, Ghired), 0 regressed.

188 = **38.2%.** PAR-30 "Tapped and attacking" — the per-opponent
distributive "**for each opponent**, [you] create a … token[ that's
tapped and attacking that opponent]" (Endless Foot Assault, Stampede
Surfer). New `CreateTokenEffect.per_opponent`: the effect's controller
makes one token per opponent, and with `attacking` each token is put into
combat against a *distinct* opponent (RULE 508.4a's defender choice made
per token, not by the shared auto-pick — verified in a 3-player game).
Parser: a leading `for each opponent,` group on the inline `create_token`
row; also generalises to the non-attacking "for each opponent, create …"
count (those cards stay blocked on other clauses — villain subtype, vote
bodies). +2, 0 regressed.

186 = **38.1%.** `_NAMED_COUNTER_KINDS` — the "put a `<kind>` counter on
X" whitelist — widened from {spore, burden, quest} with 26 more pure
card-text-driven counter kinds (charge, oil, storage, ki, verse, page,
plan, soul, fuse, depletion, flood, bounty, brick, study, plague, doom,
growth, point, infection, hatchling, pressure, slime, tide, ice, flame,
hour). Each was checked to have *no* reader anywhere in `game/`, so the
generic free-string `AddCountersEffect.kind` path models it completely.
Deliberately still a fail-closed frozenset, not a bare `[a-z-]+`: RULE
122.1e **keyword counters** (flying / indestructible / menace / …) have no
layer-engine reader, the **subsystem** counters (age / time / level /
loyalty / lore / rad / energy) are keyed off by name, and **stun / shield**
carry a replacement — all four would half-model if they slipped through.
+53, 0 regressed (charge-counter storage lands, mana batteries, Coretapper,
Firemind's Research, Long-Range Sensor — closing the counter-body gap left
by ITER 24's "you attack a player" trigger recognition).
`tests/test_par30_named_counter_kinds_widened.py`.

185 = "tapped and attacking **that player / that opponent**" trailing
defender ref (RULE 508.1). The put-from-hand (`_PUT_FROM_HAND_RE`),
look-top (`_LOOK_TOP_PUT_ATTACKING_RE`), inline-create-token
(`_TOKEN_TAPPED_ATTACKING`) and "the token enters …"
(`_CREATED_ENTERS_ATTACKING_RE`) routes gained an optional trailing "that
player"/"that opponent" — the named defender is the one the source is
already attacking, which `RulesEngine.put_onto_battlefield_attacking`
derives from the other attackers, so it's consumed, not re-modeled.
Alongside it `_SELF_SUBJECT_RE` and the `PLAYER_ATTACKED` row accept "~
attacks a player / an opponent" and "you attack a player" (the defender
kind refines nothing the bare event doesn't already carry). +1 (Soaring
Lightbringer), 0 regressed. Still open on this seam: Kaalia of the Vast
(normalize doesn't fold the legendary short name "Kaalia" → `~`), Owlbear
Cub / The Vast Scrier (qualified triggers + multi-clause bodies), the
per-opponent distributive "for each opponent, create … attacking that
player" (Endless Foot Assault, Stampede Surfer).

184 = **38.0% crossed.** "Return it to the battlefield [tapped] under its
owner's / your control[ with a +1/+1 counter on it]." (RULE 400.7
self-recursion, the "it"-pronoun continuation of a dies trigger or an
exile-then-return blink chain). New `_RETURN_SELF_TO_BATTLEFIELD_RE`
reaches the pre-existing `ReturnSelfToBattlefieldEffect` (gained
`under_your_control` / `extra_counters`) from two real shapes: a granted
DIES-trigger continuation via `_quoted_ability_grant_effects` (Feign
Death, Undying Malice — the "target creature gains '…'" quoted-grant
wrapper already existed; only the *inner* trigger body was unrecognised)
and a plain "exile ~, then return it to the battlefield under its owner's
control" blink chain (Flicker of Fate, Aethergeode Miner, Changing
Loyalty, Flickering Spirit, Fungal Fortitude, Planar Incision). +8, 0
regressed. Still open: Demonic Gifts' compound "gets +2/+0 **and** gains
'…'" wrapper (a different outer shape `_GRANT_QUOTED_ABILITY_UNTIL_EOT_RE`
doesn't match), a "face down" / "flipped" / "transformed" destination
variant (Ashcloud Phoenix, Homura, Loyal Cathar), and riders after the
return ("…and you create a treasure token", "then create a … token
attached to it", a following "It deals 1 damage…" sentence).

183 = Strive (MEC-4) recognition, one-line fix.
`normalize._strip_unregistered_keyword_labels` removes the "Strive —"
label before the segmenter runs (Scryfall lists "Strive" in the card's
`keywords` array but it is not a registered RULE 701/702 keyword), so
`_STRIVE_LINE_RE` never matched the stripped "This spell costs {cost}
more to cast for each target beyond the first." — its "Strive —" prefix
is now optional. The engine half (`AbilitySpec.strive_cost` →
`obj.strive_cost` → `effective_cast_cost` adds the cost per target beyond
the first) was already complete and tested. +9 — Aerial Formation,
Ajani's Presence, Blinding Flare, Colossal Heroics, Consign to Dust,
Cruel Feeding, Desperate Stand, Kiora's Dismissal, Rouse the Mob. A good
reminder to check the *normalized* clause, not the printed one, when a
handler "should" match.

182 = PAR-30 — the `reduce_if_targets` criteria vocabulary widened.
`_targets_reduction_criteria` now parses the phrase word by word: a bare
subtype or "X or Y" pair ("a spider", "a mount or vehicle you control"), a
"you control" / "you don't control" scope, "…token", "…with `<keyword>`",
"legendary …", and the "a `<x>` spell" stack-target forms (Mystical
Dispute, Out of Air). `continuous._obj_matches_target_criteria` grew
`legendary` / `is_token` / `controller` handling (via a threaded
`caster_id`), leaving the rest to `combat.matches_object_filter`. +10 —
Grow Extra Arms, Mystical Dispute, Out of Air, Price of Fame, Run Over,
Savage Stomp, Swampsnare Trap, This Town Ain't Big Enough, Hunter's Mark,
Mascot Interception. 0 regressed. Still open: a mana-value cap
(reanimation-spell targets — No One Left Behind, Revoke Demise) and a
"…with a +1/+1 counter on it" clause (Titanic Brawl).

181 = "This spell costs {N} less to cast **if it targets a `<criteria>`**."
(RULE 601.2f — Ajani's Response, Knockout Blow, Depower, Fantastic Bounce,
Luminous Rebuke, …; 28 SOLO cache-wide). A discount gated on the spell's
own *chosen target* rather than on board state, so `_SELF_COST_REDUCTION_
IF_RE`'s handler emits `cost_reduction` with a `reduce_if_targets`
criteria dict (tried before the board-condition `active_if` path). Engine:
`continuous.self_cost_reduction_for` gained a `targets` parameter — the
caster's already-chosen targets (RULE 601.2c precedes 601.2f); the
discount applies only when one matches (`_obj_matches_target_criteria` →
`combat.matches_object_filter`, which grew a `tapped` key). `_adjust_cost`
/ `effective_cast_cost` thread it through; `targets is None` (every
offer-time / can-cast caller) treats the discount as available so
affordability isn't understated, the same best-case treatment `help_pay`
/ kicker get. Recognised criteria: a card type (creature / permanent /
artifact / enchantment / land) plus an optional tapped / attacking /
blocking / colour qualifier. +15, 0 regressed. Still open: a *spell*
target ("a blue spell" — Mystical Dispute), a mana-value cap, "a creature
token", "you don't control", a subtype, "a legendary creature".

180 = "When you control no `<basic land type>`, sacrifice ~." (RULE 603.8
state trigger — Bog Serpent, Sea Serpent, Dandân, Island Fish Jasconius,
the original colour-gated creature cycle; 11 SOLO). Not a RULE 701
keyword-action body, but the same "residual trigger grammar" shape PAR-30
keeps turning up. `_CONTROL_NONE_SACRIFICE_RE` emits a
`LEAVES_BATTLEFIELD` trigger; the state check is `effect_binder`'s new
`controls_none_of_type` predicate — a live scan of the controller's
battlefield for that printed land subtype, **excluding the just-left
permanent** (RULE 603.6a: LEAVES_BATTLEFIELD fires while the leaving
object is still on the battlefield). Same "gate an ordinary event on a
state read rather than build a state-trigger subsystem" rationale as
`source_counters_at_least`. The ETB edge (playing the creature while you
already control none) is a documented simplification. +11, 0 regressed.

179 = PAR-30 — "tapped and attacking" cluster, batch 3, and a
higher-yield bycatch. `_DELAYED_SAC_EXILE_TAIL_RE` gained an **"at end of
combat"** timing (→ `create_delayed_trigger` step `"end_combat"`, which
`_fire_delayed_triggers` already fires) and "the token[s]" as a subject —
that tail rides on every "tapped and attacking" token card *and* on
Crumbling Colossus / the whole Basilisk morph cycle / Ohran Viper, which
is where most of the +18 came from. New `_CREATED_ENTERS_ATTACKING_RE`
segmenter idiom ("Create a token. The token[s] enter[s] tapped and
attacking." stamps `tapped`/`attacking` onto the preceding `create_token`
/ `copy_permanent`, the `_NO_REGEN_SENTENCE_RE` idiom); new
`_LOOK_TOP_PUT_ATTACKING_RE` → `impulsive_look` with
`hit_destination="battlefield_attacking"`; `CopyPermanentEffect` gained
`tapped`/`attacking`. +18 — Geist of Saint Traft, Crumbling Colossus,
Serpentine / Stone-Tongue / Lowland Basilisk, Ohran Viper, Fog Elemental,
Geist / Invocation of Saint Traft, &c. 0 regressed. Still open in the
cluster: a bare-name token subject ("Ragavan enters …" — Kari Zev),
`populate` as the created-thing (Ghired), and the multi-clause Stangg /
Living Laser bodies.

178 = PAR-30 — **"put a `<filter>` creature card from your hand onto the
battlefield [tapped and attacking]"** (RULE 508.4, the put-from-zone half
of v177's cluster). `_put_from_hand` gained a creature-subtype filter
("Soldier creature card" → `{"type": "soldier"}`, "Angel, Demon, or Dragon
creature card" → an OR list) and a colour filter ("blue or red creature
card" → `{"color": [...]}` — nothing's type line contains "blue"), plus
an optional "…tapped and attacking" tail. Derived qualities with no clean
`card_query` key ("historic", "multicolored") fail closed.
`PutFromHandOntoBattlefieldEffect.attacking` routes through a new
`"battlefield_attacking"` search destination (enters tapped, then
`put_onto_battlefield_attacking`). +7 — Preeminent Captain, Goblin Lackey,
Warren Instigator, Mindwrack Liege, Didgeridoo, Dramatic Entrance,
Firebrand Ranger. 0 regressed. Still open: the *library* "look at the top
N … put one onto the battlefield tapped and attacking" shape (Winota,
Arthur, Jet), a trailing "that opponent" defender ref (Kaalia), and
mana-value-cap filters (Shadowfax, Kinscaer Sentry).

177 = PAR-30 — **"create a … creature token that's / are tapped and
attacking"** (RULE 508.4 — Captain's Claws, Hanweir Garrison, Hero of
Bladehold, the "whenever ~ attacks, make a token" family). New
`RulesEngine.put_onto_battlefield_attacking` primitive: sets the attack
flags, auto-assigns RULE 508.4a's defender (the rest of the combat's
target if unambiguous, else the sole/first opponent), fires an `ATTACKS`
event; the token isn't *declared* so it never taps for the attack and
summoning sickness is irrelevant. `CreateTokenEffect.attacking` calls it
per made token; the ``tapped`` half stays the caller's job. Parser: a
shared `_TOKEN_TAPPED_ATTACKING` optional suffix on the plain inline-token
row, the "that many" row and the "create x … where x is" row. +10, 0
regressed. Still open in the cluster: "put a card … onto the battlefield
tapped and attacking" (Winota, Arthur — a different effect class), "the
token enters tapped and attacking" as its own sentence, and the
copy-token variant ("create a tapped and attacking token that's a copy of
…" — Calamity, Altaïr).

176 = PAR-30 — RULE 615.6 **"the damage can't be prevented"**. Two
shapes: a rider on one damage instance (`_DAMAGE_TARGET_TWO_COLOR_RE`
gained an optional "…the/that damage can't be prevented" tail →
`DealDamageEffect.unpreventable`, which flips `GameState.damage_prevention_
disabled` for the span of that one `apply()` only — Combust); and the
standalone turn-scoped clause (new `_DISABLE_DAMAGE_PREVENTION_RE` →
`disable_damage_prevention`, the effect that already existed for
hand-authored Insult // Injury but had no oracle-text route). +6 — Combust,
Flaring Pain, Impractical Joke, Unstable Footing, Pyrewood Gearhulk,
A-Ready to Rumble. 0 regressed. Closes the colour-list cluster tail.

175 = PAR-30 — a **combat-state** tail on the destroy-colour-adjective
target. `_DESTROY_COLOR_ADJ_RE` gained an optional "…that's attacking or
blocking / attacking / blocking" group → a `creature_filter` boolean;
`combat.matches_object_filter` gained `blocking` / `attacking_or_blocking`
keys (the siblings of the pre-existing `attacking`, checked via
`blocking_attacker_ids`). +1 — Surge of Righteousness. 0 regressed.
Gideon's Defeat also uses "that's attacking or blocking" but stays
UNMODELED on its "if it was a Gideon planeswalker" conditional tail.

174 = PAR-30 — the colour-list target reaches the **graveyard** zone, and
"it gains `<kw>` until your next turn" on a **previous-clause subject**.
`_color_word_list` is the N-colour generalization of `_two_color_letters`
(≥3 colours: "red, white, or black"); `_EXILE_FROM_GRAVEYARD_RE` gained an
optional `(?P<colors>…)` group → `exile` spec's `colors` → the
`ExileEffect` `TargetSpec.colors` already threaded at v170. `targeting.
legal_targets`' graveyard-card branch gained the `_color_ok` call every
battlefield branch already had. New `grant_until_previous` handler
(`_GRANT_UNTIL_PREVIOUS_RE`, `previous_subject_only`) — "It gains haste
until your next turn." binding "it" to the just-created token copy, the
`_lockdown` / `_return_to_hand_previous` idiom. +2 — Offspring's Revenge
(exile RWB graveyard creature → 1/1 copy token → haste), Bond of Revival.
0 regressed.

172-173 = PAR-30 v172 (colour-list `TapEffect.colors` + `_TAP_TWO_COLOR_
RE` → Tidebinder Mage; compound `_RETURN_SELF_AND_TWO_COLOR_RE` → Snow
Hound, +2) landed folded into the MEC-46 v173 commit (the two batches
were interleaved across `effects.py`/`handlers.py`/`gate.py`); MEC-46
itself is the RULE 701.38 vote-outcome-body primitives (see
`Done_Backend.md` "Vote"), +6.

171 = PAR-30 — the colour-list target extended to bounce / put-on-
library / graveyard-recursion. `ReturnToHandEffect` /
`ReturnToLibraryEffect` / `ReturnFromGraveyardEffect` each gained a
`colors` param → `TargetSpec.colors`; three dedicated
`_RETURN_*_TWO_COLOR_RE` handlers (Escape Routes, Hunting Drake, Crypt
Angel). Also plugged a latent gap: the `creature_you_control` /
`land_you_control` / `other_creature_you_control` branch of
`legal_targets` never applied `_color_ok` — added, a no-op unless
`colors`/`color` is set. +3, 0 regressed. Still open in the cluster:
Combust (needs a per-instance "damage can't be prevented" flag), Snow
Hound (compound "return ~ and target …"), Tidebinder Mage (the
"doesn't untap …" tail), Surge of Righteousness ("that's attacking or
blocking" + "you gain 2 life"), Offspring's Revenge's 3-colour list.

170 = PAR-30 — the same colour-list target extended to removal:
`_DESTROY_COLOR_ADJ_RE` widened to a "`<c1>` or `<c2>`" adjective + an
optional "with `<kw>`" tail (Deathmark, Wallop); new
`_EXILE_TARGET_TWO_COLOR_RE`/handler (Celestial Purge). `DestroyEffect` /
`ExileEffect` gained a `colors` param threaded into their `TargetSpec`,
mirroring `DestroyEffect.color`'s single-letter form. Same-colour-twice
rejected. +3, 0 regressed. Still open in the cluster: damage tails
(Combust "the damage can't be prevented"), return-from-graveyard (Crypt
Angel, Dreams of the Dead), bounce (Escape Routes, Snow Hound),
put-on-library (Hunting Drake), tap (Tidebinder Mage), and
Offspring's Revenge's 3-colour list.

169 = PAR-30 (villainous-choice / reanimator-token residue) — a
colour-list creature target on the pump family. "target `<c1>` or
`<c2>` creature gets +N/+M / gains `<kw>` until end of turn" — the
Weaver cycle (Hate/Rage/Sky/Might/Spirit Weaver, Sootstoke Kindler,
Wilderness Hypnotist). `PumpEffect` gained a `colors` param threaded
into its `TargetSpec`; `TargetSpec.colors` + `targeting._color_ok` were
already wired into `legal_targets`, just never reached from a pump. New
`_PUMP_TARGET_TWO_COLOR_RE`/handler, the `_DAMAGE_TARGET_TWO_COLOR_RE`
sibling (the shared `TARGET` macro carries no colour slot). +7, 0
regressed. (Offspring's Revenge — the reanimator-token card with the
same "red, white, or black" filter — stays UNMODELED on its 3-colour
list + its own copy/haste tail.)

168 = PAR-30 (reanimator-token residue) — "return [up to] X target
`<type>` cards from [scope] graveyard to your hand / the battlefield"
(Death Denied, Entreat the Dead, Wildest Dreams; narrows Wake the Dead /
Shattered Crypt / Champion of Stray Souls). The count is the spell's own
announced {X}, read at target-gathering time via `TargetSpec.
count_selector="source_x_paid"` — the March of Swirling Mist / Change of
Plans idiom. `ReturnFromGraveyardEffect` gained a `count_selector` param
threaded into its `TargetSpec` plus a multi-target apply branch that
takes every pick the targeting layer offered (its printed
`effective_count` stays 1). New `_RETURN_FROM_GRAVEYARD_X_RE` / handler,
tried before the numeric-N plural handler. +3, 0 regressed.

167 = PAR-30 (Vote residue) — "planeswalk" / "chaos ensues" outcome
bodies. Two new no-param effect types (`effects.PlaneswalkEffect` /
`ChaosEnsuesEffect`) wrapping `RulesEngine.planeswalk` (RULE 901.10) and
the new `RulesEngine.trigger_chaos` (RULE 901.13, factored out of
`roll_planar_die`, now a genuine no-op with no active plane). Closes Path
of the Animist / Path of the Enigma through `_vote_majority`'s body
parse. Fullmatch-only: "planeswalk to <plane>" (Seek Bolas's Counsel),
"you may planeswalk" (TARDIS) stay UNMODELED. +2, 0 regressed.

166 = PAR-30 (Vote residue) — plain "take an extra turn after this one"
effect-body handler, wired to the pre-existing `take_extra_turn` effect
type (`effects.TakeExtraTurnEffect` / `GameState.extra_turns`), which
nothing in the parser emitted before. Closes the modelable half of Plea
for Power's vote outcome plus a wide temporal spill (Time Walk, Temporal
Manipulation/Mastery/Trespass, Capture of Jingzhou, Part the Waterveil,
Alrund's Epiphany, Timestream Navigator, Time Sieve, Teferi Timebender,
…) — +13. `_vote_per_vote` fail-closes on a `take_extra_turn` body (no
int `count`/`amount` to scale by the tally — Expropriate). Riders that
stay their own tickets: "skip the untap step of that turn" (Savor the
Moment), "…you lose the game" (Last Chance), "…for each coin that comes
up heads" (Ral Zarek). 0 regressed.

165 = PAR-30 (Vote residue) — `_vote_per_vote` now carries a leading
"each player / each opponent" subject off segment 0 onto a subject-less
later segment it's split from by a bare "and" (Capital Punishment: "each
opponent sacrifices … for each death vote **and** discards a card for
each taxes vote" — the discards clause is still each opponent's). "you"
stays fine as its own segment subject; a later segment naming a
*different* scoped subject still fails closed. +1.

164 = PAR-30 (Vote residue) — Living Death mass graveyard recursion.
`ReturnFromGraveyardEffect.players` ("you" / "each_player") — a mass,
untargeted return over every matching graveyard card, run through the
existing `_apply_one` (ETB prohibition, owner control, riders);
`_MASS_RETURN_GRAVEYARD_RE` claims "[each player returns / you return]
all/each creature card[s] from [their/your] graveyard to the
battlefield/hand". `_vote_majority`'s "a targeted branch can't resolve
off-stack" guard narrowed to spare a `players`-scoped (untargeted)
branch. +2 (Empty the Catacombs; Magister of Worth — both vote branches
now modeled, combined with v163's destroy branch). Still open in this
cluster: riders on the returned cards (Pyrrhic Revival's -1/-1 counter,
Storm of Souls' "each is a 1/1 Spirit"), and "…that weren't put there
this way" (Bringer of the Last Gift).

"Covered" = parser-`MODELED` **or** hand-`AUTHORED`. Re-run the report rather
than trusting a figure quoted here, in `CLAUDE.md`, or in the Engine-Status
tab; after any change here, sync all three.

**Bump `PARSER_VERSION` (`parser/oracle/gate.py`) in the same session you add
a handler.** The ledger is keyed on content-hash **+ version**, so measuring
twice within one batch (bump, measure, add more handlers, measure again)
silently reuses the first run's rows. Either bump again or delete that
version's rows. Hand-authoring alone needs no bump — `content_hash` folds in
`ability_catalogue.is_registered`.

## How the tail gets closed

The remaining ~25k templates are, by construction, not generic. This is an
*indefinite program*, not a finite batch list, and proceeds two ways:

1. **Narrow parser extensions** for singleton shapes that still generalize a
   little — a slightly different targeting scope, a compound filter.
   Preferred: each still pays off across a small cluster.
2. **Hand-authoring** genuinely unique cards in `game/ability_catalogue.py`
   ([authoring guide](../Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)),
   only after confirming no near-miss handler would unlock a cluster.

Deterministic-first: classification, scaffolding and measurement are pure
code, no LLM. LLM/subagent effort (Sonnet/Haiku only, file-ownership waves)
goes only to finalizing a handler's regex/builder semantics and to
hand-authoring the tail.

A few items are deliberate non-goals — the legacy pre-2021 werewolf
template, silver-border/acorn/un-set cards — excluded from the denominator or
accepted as permanently unmodeled. Stickers and Attractions are project
non-goals tracked in [BACKLOG.md](BACKLOG.md) under MEC.

## Two tracks: basic mechanics vs. set-specific mechanics

The tail isn't one undifferentiated pile — every unclaimed template falls
into one of two tracks, and they get worked by two different prioritization
rules, not one:

- **Basic mechanics** — an oracle-text *shape*, keyword-action, or template
  that recurs across many sets and years (a modal wrapper, a P/T
  characteristic-defining ability, an O-Ring variant, a targeted-destroy
  compound, or a keyword *action* like Investigate/Explore/Scry that a
  design team keeps reprinting set after set once it exists). Worked by raw
  cache-wide yield (`parser_probe.py rank`/`blocked`) — a fix here keeps
  paying off on sets not yet printed, so the biggest SOLO count wins
  regardless of which deck happens to need it today. This is the default
  track and where most of this document's worked examples live.
- **Set-specific mechanics** — a RULE 702 keyword *ability* or *action*
  that a design team built for, and largely confined to, **one expansion or
  Commander-precon product line** (it may get one or two nostalgia reprints
  years later, but no ongoing set keeps printing new cards with it). A fix
  here only pays off for decks actually built around that product — so it's
  worked **deck-first**: when auditing a saved deck whose commander (or the
  deck itself) comes from a named set/precon, check that set's own
  signature mechanic(s) against the table below *before* falling back to
  generic cache-wide ranking, since a single precon commonly clusters a
  dozen+ of its own set's cards into one saved deck.

  A mechanic only belongs in this table once someone has actually run
  `parser_probe.py blocked "<its regex>"` and confirmed real cards are
  blocked on it — a name alone (guessed from a set's marketing copy) isn't
  worth an entry; verify, then add the row. Extend this table as each
  deck's audit turns up its set's mechanic, rather than trying to
  pre-populate every named product's keyword in one pass.

  | Mechanic | RULE | Set / product | Status (as of date checked) |
  | --- | --- | --- | --- |
  | The Ring tempts you | 701.51/701.52 | Tales of Middle-earth | **Done** — `Player.ring_level`/`ring_bearer_id` (`Done_Backend.md`, cEDH-cube batch); the oracle-text clause itself and "whenever the Ring tempts you, `<effect>`" (`EventType.RING_TEMPTED`) followed later (2026-08-05) |
  | The One Ring's own bespoke clauses (protection-from-everything-on-cast, burden-counter life loss, burden-counter draw scaling) | — | Tales of Middle-earth (one unique card) | **Partially done** (checked 2026-08-05) — "burden" is now a recognized named counter kind, but the card's other two clauses are still unclaimed; likely hand-authoring territory (RULE 122.1a's burden-counter card is a singleton, not a cluster) |
  | Frodo, Adventurous Hobbit (this deck's own commander) | — | Tales of Middle-earth | **Done** (2026-08-05) — `GameState.life_gained_this_turn` (new per-turn tracker) + `EffectSpec.condition`'s `"is_ring_bearer"`/`"ring_tempted_at_least"` keys, `effects.ConditionalEffect._condition_holds` generalized to AND multiple condition keys together. The same `"is_ring_bearer"` key also closed Aragorn, Company Leader/Faramir, Field Commander's "if you chose a creature other than ~" clause (each still has one unrelated second gap of its own) |
  | Frodo, Sauron's Bane (the same DFC's back face) | — | Tales of Middle-earth (one card) | **Done** (2026-08-05) — hand-authored in `ability_catalogue.py`, no new engine primitive after all: a two-step RULE 613.6 standing conditional static driven by a plain custom counter, `ActivationCost.activation_condition` settable straight off a hand-authored `cost` dict, and a new `ConditionalEffect.ring_tempted_at_most` + `grant_triggered_ability`'s own `grant_effects` honouring a per-entry `condition` for the "…otherwise…" branch — see `Done_Backend.md`'s "Frodo, Sauron's Bane" entry |
  | Choose a Background | 702.124 | Commander Legends: Battle for Baldur's Gate | **Done** (2026-08-05) — bare FLAG keyword, inert in-game like Partner; the deckbuilding pairing check itself is [BACKLOG.md](BACKLOG.md)'s DB-3, still open |
  | Magecraft | ability word | Strixhaven | **Done** — `segmenter._MAGECRAFT_RE` |
  | Amass / Mutate / Monstrosity / Adapt / Goad / Bargain / Fading / Soulbond | 701.x / 702.x | War of the Spark / Ikoria / Theros / various | **Done** — see `Done_Backend.md`'s cEDH-cube batch |
  | Day/Night (werewolf transform) | 702.28 (2011+ template) | Innistrad: Midnight Hunt/Crimson Vow | **Done** — the *legacy* pre-2021 template is the one accepted non-goal above |
  | Specialize | digital/Alchemy (no paper CR) | Alchemy Horizons: Baldur's Gate | **Partially done** (2026-09-03, MEC-48) — `catalogue/keywords.py` recognizes a bare "Specialize {cost}" line; `effect_binder._specialize_activated_ability` binds it to a real sorcery-speed "{cost}, Discard a card" activated ability whose body is `SpecializeEffect` (a persistent `GameObject.is_specialized` designation + `EventType.SPECIALIZED` — **no** characteristic swap; the five per-colour specialized faces aren't in this repo's Scryfall seed, documented simplification); `segmenter._TRIGGER_VERBS` gains "specializes" → `SPECIALIZED`. +6 bare-cost cards (Gale/Jaheira/Rasaad/Vhal/Viconia/Wilson) + several specialized faces whose "when ~ specializes, `<modeled effect>`" body now parses. **Still open:** the "Specialize {cost}. `<rider>`" cards (cost-reduction / "activate only if" / alternate-zone riders) are held UNMODELED by `_SPECIALIZE_WITH_RIDER_RE` — each rider is its own small activated-ability-modifier follow-up (~5 cards: Imoen/Karlach/Shadowheart/Lukamina/…). |
  | Starting intensity | Duskmourn's Room-adjacent template | Duskmourn: House of Horror | **Not done** (checked 2026-08-05) — 0 cards SOLO-blocked on the phrase alone (always paired with another unclaimed clause); needs its co-blocker identified before estimating real scope |
  | Learn (Lessons) | 701.50 | Dominaria / Strixhaven | **Partially done** (checked 2026-08-05) — bare "Learn." is a 7-card SOLO cluster; the Lesson-sideboard-zone infrastructure itself (RULE 701.50a "look at your sideboard") isn't built, so a full deck with real Lessons stays out of scope regardless |
  | Investigate | 701.19a | Shadows over Innistrad (**reused across many later sets** — belongs on the *basic* track, listed here only as the worked example that motivated this split) | **Done** (2026-08-05) — a `create_token` alias onto the already-shipped Clue token, 87+ cards in one row; this is the case study for "keyword action, but basic not set-specific" — check *reuse breadth* before filing something here |
  | Station | 702.184a / 721 | Edge of Eternities | **Done** (2026-08-27) — a third "striated text box" grammar alongside Leveler/Class (`catalogue/station.py`), the reminder-line activated ability bound structurally off Scryfall's own `keywords: ["Station"]` entry (`effect_binder._station_activated_ability`); see `Done_Backend.md`'s Station entry |
  | Horsemanship | 702.31 | Portal (Portal-only, no reprints since) | **Not done** (checked 2026-08-27, RULE 702 keyword audit) — bare keyword, `combat.can_block` never checks it; lowest priority of this whole table, essentially a dead card pool |
  | Banding | 702.22 | Alpha/old-border era | **Not done** (checked 2026-08-27) — bare keyword, 0 `game/` hits; nostalgia-only, no modern reprints |
  | For Mirrodin! | 702.90-adjacent | New Phyrexia | **Recognition fixed** (PARSER_VERSION 101, PAR-28) — the trailing-`!` keyword line is now claimed (`_KEYWORD_TOKEN_RE`); no engine behaviour (Living Weapon-style germ token) yet |
  | Max Speed / Start Your Engines! | RULE 702.178 / 702.179 | Aetherdrift | **Done** (PARSER_VERSION 101, PAR-28) — full Speed subsystem: `Player.speed`, the Start-Your-Engines! SBA, the RULE 702.179d life-loss inherent trigger, `your_speed_is_max` static gate. See `Done_Backend.md`'s "Keyword — [ability] families" entry |
  | Job Select / Tiered / Increment / Paradigm / Teamwork / Sneak | various | Final Fantasy | **Not done** (checked 2026-08-27) — recognized-but-inert; Sneak's name also collides with an unrelated hand-authored effect, worth disambiguating before building. (**Power-up** was in this row — now **done**, PAR-28) |
  | Space Sculptor | — | Warhammer 40,000 (Commander) | **Not done** (checked 2026-08-27) |
  | Living Metal / More Than Meets the Eye | — | Transformers (Commander) | **Not done** (checked 2026-08-27) |
  | Web-slinging | — | Spider-Man | **Not done** (checked 2026-08-27) |
  | Firebending / Mobilize | 702.189 / 702.181 | Avatar: The Last Airbender / Tarkir: Dragonstorm | **Recognition done, behaviour not** (PARSER_VERSION 100, PAR-27) — "Firebending X, where X is …" / "Mobilize X, where X is …" no longer drops the card to `UNMODELED` for a formatting reason (the keyword line is claimed, inert — same as a plain "Firebending 2"); the variable-N token/damage behaviour is still unbuilt |
  | Infinity | — | (product TBD at audit time) | **Not done** (checked 2026-08-27) — 0-2 cache hits |
  | Warp | 702.185-adjacent | Bloomburrow | **Not done** (checked 2026-08-27) — distinct from the unrelated "Warp" collision noted for the Final Fantasy row above; verify regex scoping before building either |
  | Exhaust, Solved, Boast, Forecast | RULE 702.177 / 702.169 / 702.142 / 702.57 | Edge of Eternities / Murders at Karlov Manor / Kaldheim / Dissension | **Done** (PARSER_VERSION 101, PAR-28) — the whole "Keyword — `<ability>`" label family bound with its real restriction (Exhaust/Power-up once-per-game, Boast attacked-this-turn + once-per-turn, Forecast from-hand + upkeep-only, Solved's Case solve state machine). Per-card oracle coverage of individual Cases is still long-tail (an unbuilt "N …this turn" solve-condition tracker, or an effect-body gap in a `Solved —` clause) — the *mechanism* is done, same standing as the battle pool. See `Done_Backend.md`'s "Keyword — [ability] families" entry |
  | Mayhem, Decayed | various | Duskmourn: House of Horror | **Not done** (checked 2026-08-27) — Decayed also has real combat-restriction implications (can't block, 2 damage then sacrifice), not just a cost/cast wrapper |
  | Double team (+ Conjure / Draft from a spellbook / Boon / perpetual) | — (Alchemy digital keyword, no CR RULE 702 number) | Alchemy Horizons: Baldur's Gate / Dominaria | **Not done** — noted by PAR-27's keyword audit (2026-08-28): "Double team" is absent from `catalogue/keywords.py`'s CR-scoped `_TABLE`, so "Flying, double team" / "Menace, double team" lines fail `is_keyword_line`. ~18 cache cards, all also-blocked on other unmodelled Alchemy mechanics (Conjure/Draft/Boon/perpetual). Recommend deciding the whole Alchemy keyword family as one unit (likely a non-goal like Vanguard — Alchemy cards aren't paper-Commander-legal, so they're outside the `--commander-legal-only` coverage scope anyway) rather than adding "double team" piecemeal |

  The rows above come from a 2026-08-27 systematic audit of all 195
  registered `parser/oracle/catalogue/keywords.py` entries against real
  `game/` consumers (not just cache LIKE-counts) — see `BACKLOG.md`'s
  `PAR-22` through `PAR-26` for the audit's full findings, including the
  **evergreen** gaps it found alongside these set-specific ones (Prowess,
  Affinity, Delve, Shroud, and a dozen others — those belong on the
  *basic* track, not this table, since they recur every set rather than
  being confined to one product). Several of the rows above are still first-pass
  cache-count estimates (0-2 hits at audit time, not yet `parser_probe.py
  blocked`-verified per this section's own rule) — verify before sizing a
  build, don't just copy the status.

  Doctor's companion / Time travel (Doctor Who), Augment (Aether Revolt),
  ki counters (Kamigawa block), and whatever Lorwyn Eclipsed/New
  Capenna/further Bloomburrow-block sets turn out to print as their own
  signature mechanic are all **known-unverified** — real cards may be
  blocked on some of these phrases (see `rank`'s live output), but nobody
  has yet confirmed scope/primitive-existence for them the way the rows
  above were. Don't copy a status onto this list without running the
  check yourself.

## Lessons that keep recurring

Each was paid for once; re-reading them is cheaper than re-learning them.

- **A ranked template that is a block *wrapper* (modal, Saga, Class level) is
  usually a red herring.** `gate.py` fail-closes the whole block when any one
  mode body fails, appending *every* body to `unclaimed` — so the wrapper
  shows up in the ranking as a proxy for "some sibling clause still has a
  gap". Re-derive which sub-clause actually fails before trusting a
  template's face-value card count.
- **The all-or-nothing coverage gate makes every batch-plan estimate an
  overcount.** Most cards blocked by a template have *other* unclaimed
  clauses too. A family whose primitive is correct and tested can still
  yield literally zero newly-covered cards.
- **A plan-doc row's own framing can be wrong.** Escape/Kicker/Multikicker
  were documented as "new keyword mechanics" but were already fully modeled
  — the real blockers were two recognition bugs. Sample real cards before
  accepting a stated scope.
- **When a handler's regex has a subject alternation, check every
  alternative is actually read out.** `_lose_life` and later `_discard` both
  matched "target player …" but never threaded `target_kind` through, so
  both silently applied the effect to the source's controller instead.
- **When a general regex fix passes the happy path, write the adversarial
  "why doesn't this over-match" test before trusting it.** A general
  keyword-line split looked correct until `"flying, then draw a card"`
  caught it; it was replaced with a narrow closed list.
- **Parse-only tests aren't enough — write execute tests.** Two shipped
  effect families passed the whole suite yet crashed on first real use
  (`Zone` imported under `TYPE_CHECKING` only; `legal_targets` missing a
  branch and silently returning `[]`). Also: new selector params must be
  whitelisted in `effects._SELECTOR_KEYS`, or they are silently dropped.
- **A ticket that reads as "N more rows in a whitelist" is worth
  re-measuring before you write the rows.** MEC-14 listed four condition
  phrasings as four independent entries; the biggest of them turned out not
  to be a new *kind* at all but a new **subject** ("as long as *enchanted
  permanent* is a creature" is about the Aura's host, not the Aura), and one
  `of` key made every existing kind work on that subject for free. Two of
  the other three then needed no more than the row the ticket predicted. The
  general lesson: when several ticket items share a shape, look for the
  axis they vary along before adding one entry per item.
- **"Needs a new primitive" is worth re-checking against the phrasing.**
  MEC-14's soulbond item was blocked on nothing at all in the engine — the
  ``soulbond_pair`` selector had shipped with the cEDH cube batch and simply
  had no oracle phrase that could reach it. Three parser rows closed it.
  This is the same failure mode `CLAUDE.md`'s batch-discipline rule
  describes, seen from the other end.
- **Ticket card estimates are wrong in both directions, and the wrong
  *shape* is the expensive kind.** MEC-12(a) described a variable target
  count as "Death Kiss, 1 card". Death Kiss really is the only card with
  that phrasing — but four *other* cards print "for each opponent, goad up
  to one target creature that player controls", which is the same feature
  with an already-shipped constraint (`distinct_controllers`) doing the rest.
  Measuring the *mechanism* rather than the quoted phrase turned a
  one-card item into a five-card one at no extra cost.
- **Scryfall's own `keywords` array is noisy — cross-reference before
  treating a raw string as a real keyword.** It mixes RULE 702 keyword
  *abilities* (what `catalogue/keywords.py` tracks), RULE 701 keyword
  *actions* (Mill/Scry/Investigate — a structurally different mechanism,
  ordinary verbs handled by `handlers.py`), created-token type names
  (Treasure/Food), and — the majority by distinct-string-count — one-off
  card-specific *flavor* ability names Scryfall's own keyword-extraction
  heuristic mistakes for a reusable keyword whenever a card prints the
  "Name — effect" ability-word template with a novel name ("10,000
  Needles", Jumbo Cactuar). A diff of "every distinct raw `keywords`
  string not in our registry" (2026-08-28) found 689 distinct strings —
  almost none of them a real registry gap; see `normalize.
  _strip_unregistered_keyword_labels` (PARSER_VERSION 99) for the fix this
  specific noise pattern led to.
- **At scale, "verify before sizing" can invalidate an entire `rank`
  top-N in one pass, not just one entry.** 2026-08-28 (was ticket PAR-20,
  now closed): six of the highest-count templates in a fresh cache-wide
  `rank` (40-240 raw hits each — "choose N —", "you get an emblem with
  `<name>`", "costs `<cost>` more … for each target beyond the first", the
  O-Ring "exile … until ~ leaves", "enchanted creature has `<name>`", the
  2011+ werewolf transform condition) were checked with `parser_probe.py
  blocked`, and *all six* turned out to already be fully claimed by
  existing grammar — every card's real blocker was a distinct, unrelated,
  one-off co-resident clause (`blocked`'s "what else blocks those cards"
  residue came back essentially all count-1). This isn't a one-off miss;
  it's a sign the basic-mechanics (cache-wide) track's easy big wins are
  genuinely thinning out at the current coverage level (~35.5%), not just
  a bad `rank` run. The one discrete win squeezed from that residue
  afterward — RULE 604.3's "power and toughness are each equal to the
  number of `<X>`" CDA-P/T handler (PARSER_VERSION 105, +20 cards) — was
  the exception that proves it: a genuinely unrecognized shape, but a
  narrow whitelisted one, not a big generic family. When this happens,
  don't keep re-running `rank` hoping for a better top-N — switch to the
  deck-first track instead (a real saved deck's cards are far more likely
  to share an actual unfixed pattern than the whole-cache aggregate is at
  this point).
- **"Coverage" and "actually playable" are two different claims — check
  both.** Three separate PAR-6..10 (2026-08-03) cards were already
  `MODELED` (the coverage gate satisfied) while being functionally inert: a
  bare Cycling keyword was claimed but bound to no real activated ability
  (PAR-9); a layer-6 grant reaching the *hand* zone populated
  `granted_activated_abilities` correctly, but `legal_actions`' hand-zone
  loop only ever scanned `activated_abilities`, so the granted one was
  never offered (PAR-8); and `can_activate` had no branch at all for an
  ability sourced from the *graveyard* zone, so a new "return this card
  from your graveyard to the battlefield" effect would have been unusable
  the moment it shipped (PAR-10). None of these show up in a coverage
  diff — only playing the card (or writing an execute-level test that
  calls `legal_actions`/`can_activate`, not just `bind_from_catalogue`)
  catches them. Grep for the *offering* code path, not just the binding
  one, whenever a new effect targets a zone/ability-list combination
  nothing has used yet.
- **A ticket's own example can be hiding a much bigger, unrelated family
  one clause away.** PAR-10 was framed as "Jin-Gitaxias's compound
  activation condition" (a handful of cards). Sizing its SOLO list turned
  up Dread Wanderer blocked on a *second*, wholly unrelated clause: "Return
  this card from your graveyard to the battlefield[, tapped]." was
  entirely unrecognized — 69+ cache cards, by far the batch's biggest win,
  found only by running `blocked` on the literal phrase inside a
  "ALSO BLOCKED" card's *other* unclaimed line rather than stopping once
  the ticket's own named clause was handled.

## Worked example: the battle pool (RULE 310)

The battle *card type* is fully implemented (see `Done_Backend.md`,
"Card-type & structural coverage"), which makes this pool a clean sample of
what the tail is actually made of: **12 of 39 cached battles are MODELED**,
and the other 27 fail on ordinary effect-body grammar with nothing to do with
battles as a type. Grouped by what each actually needs, most-cards-first:

- **"you may `<cost>`. If you do, `<effect>`."** — Occupation of Kulrath,
  Invasion of Mercadia, Invasion of Ergamon. **The engine primitive already
  exists**: `RulesEngine.request_pay_cost_then` (RULE 118.3, built for Mana
  Vault and the Pacts, with an "if you don't" branch). This is a *parser
  handler only*. Do not re-defer it as "needs a primitive" — highest-yield
  item here and the natural next one to take.
- **"search your library and/or graveyard"** — Invasion of Ikoria, Invasion
  of Arcavios (the latter also "outside the game"). Same blocker as the
  Doomsday/Finale entry; closing that closes these.
- **Multi-target "up to N target creatures each get …"** — Invasion of
  Kylem. `TargetSpec.count` already models N≥2 for destroy/exile/damage; the
  pump family is still N=1-only.
- **Mass damage with a compound selector** — "each creature **and each
  planeswalker**", Invasion of Karsus. The selector damage handler takes one
  selector, not a union.
- **X-scaled token creation** — "create X 2/2 … tokens", Invasion of New
  Phyrexia. `COUNT_X` exists as a fragment; the create-token handler doesn't
  use it.
- **The bespoke tail, one card each** — hand-authoring territory rather than
  parser work: stun counters (Kamigawa), "for as long as that card remains
  exiled, its owner may play it" (Gobakhan), "exile all cards from your hand,
  then draw that many" (Kaldheim), manifest (The Battle of Dragon Brothers),
  reflexive "when you do" triggers (New Capenna, Tarkir), fight-after-counter
  (Muraganda), "isn't exactly two colors" (Ravnica), power-X-or-less destroy
  (Lorwyn), "nonbattle permanent card" (Tolvada), scry-then-conditional-draw
  (Pyrulea), "sacrifices a creature or planeswalker of their choice" (Azgol),
  dig-until (Alara), a modal "choose one or both" ETB (Fiora), a phase
  trigger on "your combat step" (Occupation of Llanowar),
  search-for-a-typed-card-to-hand (Theros), look-at-top-N-reveal-one
  (Ixalan), and multi-clause mill/discard/draw (Amonkhet).

**What this sample shows.** One line of shared grammar —
`normalize._SELF_REFERENCE_RE` folding "this battle"/"this Siege" to `~` —
moved the pool 0 → 12, while the *card type* work itself moved it zero. The
gains that matter are almost always in shared grammar, and a fully
implemented mechanic is no guarantee its cards parse.

## Worked example: dungeon rooms (RULE 309)

Same lesson from the other direction: the RULE 309 dungeon engine and all
four room graphs (`game/dungeons.py`) were fully built while sitting at
21/30 modeled rooms — nothing dungeon-specific was missing, only ordinary
effect-body grammar (`room_effect_specs` runs the exact same
`segmenter.parse_effect_body` a card's own text does). PAR-13 (2026-08-04)
closed 8 of the 9 gaps: a P/T-delta route for `grant_until` plus its
"can't attack/block until `<duration>`" sibling (Fungi Cavern/Twisted
Caverns — both also picked up real non-dungeon cards via two new `_GROUP`
phrasings); a mandatory compound discard-then-triple-sacrifice handler
(Oubliette); a legendary named token (Cradle of the Death God — the first
`Card.is_legendary` a synthesized token ever carried); `ImpulsiveDrawEffect`'s
first oracle-text route, previously hand-authored-only (Runestone Caverns);
a new `DrawRevealCastOneFreeEffect` + a `"cast_free"` `choose_objects`
action, the first hand-zone pick that chooser ever offered (Mad Wizard's
Lair); and a new mass-interactive primitive, `RulesEngine.
request_each_player_pay_or` (RULE 101.4 APNAP, chained off the existing
single-player `request_pay_cost_then`) for "each player loses N life
unless they `<pay cost>`." (Veils of Fear/Sandfall Cell — the latter also
needed a new compound `ActivationCost.sacrifice` value,
`creature_artifact_or_land`, since the plain single-word sacrifice grammar
can't express an OR of three types).

**Throne of the Dead Three** ("Reveal the top ten cards of your library.
Put a creature card from among them onto the battlefield with three +1/+1
counters on it. It gains hexproof until your next turn. Then shuffle.")
is the one room left unmodeled — a genuine "reveal top N, choose one
matching a filter, place it with counters, shuffle the rest back" shape,
confirmed to have zero non-dungeon cache siblings (unlike every other gap
above, so there's no shared-grammar win waiting behind it). Left as an
honest residual rather than forced, the same call this document already
makes for the battle pool's own bespoke-tail cards.
