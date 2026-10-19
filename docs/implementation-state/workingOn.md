# Working on — resumable state of the ticket in progress

**The working memory for a ticket that is being built right now.** It exists so that a
new session — after the prompt cache expired, a crash, an update, a context compaction —
continues exactly where the last one stopped instead of re-deriving the state from the
code, the git log and the backlog.

Rules:

- **Read this file first** when you start or resume work on any ticket. If your ticket has
  a block below, continue from its *Next step*; do not re-evaluate what it records as done.
- **One block per ticket in progress**, headed `## <TICKET-ID> · <title>`. Several sessions
  may share this working tree, so never edit another ticket's block.
- **A partly done ticket's residue lives here, not in `BACKLOG.md`.** When a run ends with
  part of the ticket still open, keep its block and record under *Residue* exactly what is
  left (card clusters, blockers, which cards each needs) plus the *Next step*; `BACKLOG.md`
  keeps only the ticket's terse open point (id, title, one-clause scope).
- **Update the block at every milestone**, not only at the end: after a sub-step is built
  and tested, after a decision, before a long-running command (full test tier, coverage
  run), before a commit. Write it so a reader with *no* conversation context can act on it.
- Keep it terse and current — replace stale lines instead of appending. Keep only
  the current resumable state; session logs belong in unversioned temporary files.
- **On closing the ticket, delete its whole block.** Durable results for shared
  engine/parser features belong in `Done_Backend.md` / `Done_Frontend.md`;
  individually modeled cards stay documented in their implementations and tests,
  not in `Done_Backend.md`. A ticket is closed only once its residue is done too.
  With no ticket in progress this file is just this header and the empty template
  — no ticket id, no log.

Block template (do not change this, copy below the line, fill in there):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-132 · Dependent target/body follow-up batch

- **Started / last update:** 2026-10-19 / 2026-10-19
- **Goal of this run:** re-size every calibrated PAR-132 row (`PARSER_LONG_TAIL.md`, "PAR-132 calibration") with `parser_probe.py` at the current PARSER_VERSION, then land the highest-yield shared shapes via existing primitives.
- **Done (built + tested):** v688 (+8 / -0) and v690 (+24 / -0 vs v688; 21,812 / 35,046 covered, authoritative 62.2%; snapshot diff vs v687: +32 / -0). v688: (a) `for each [nontoken] <type> destroyed/exiled this way, <body>` -> `for_each` over `{"this_way": verb, ...}` (Hour of Need, Descent of the Dragons, March of Souls, Rampage of the Clans, Blood Money, Canoptek Scarab Swarm); (b) "that spell or ability's controller" / "that player" loses life / takes damage under a BECOMES_TARGET head (marker `event_player_events`, `gate._event_player_antecedent_ok`): Ashenmoor Liege, Retromancer. v689/v690 (segmenter `_any_number_this_way_specs`, `_exiled_this_way_conditionals`; handlers `counter_that_spell_or_ability`, `spell_controller_sacrifices`): (c) "<tap/sacrifice/return/discard> any number of X. <body> for each X <verb>ed this way" = one `choose_objects` pick (`permanent_filter` from `parse_count_phrase`, `require_untapped`, `pool_zones: ["hand"]`) whose `then_that_many` body is the for-each `bind` over `{"kind":"fixed","amount":"x"}`; counted noun must equal or broaden the pool noun; body with a target refused. Cards: Harmony of Nature, Marshaling the Troops, Jaddi Lifestrider, Guild Summit, Minas Tirith Garrison, Ledev Champion, Orphans of the Wheat, Siege Striker, Devout Invocation, Charge Across the Araba, Renounce, Sacred Rites, Mind Maggots. (d) "discard your hand[, then draw N]. ... for each card discarded this way" on the same pick (mandatory, whole hand): Pyretic Charge, Malfegor. (e) "<exile ...>. If a [non]creature card was exiled this way, <body>" -> new condition `this_way_pool` (`pool` exiled/destroyed, `card_type`, `negate`; whitelisted in `spec.py` `_STRUCTURED_CONDITION_FIELDS`) over `GameContext.exiled_objects`; parser claims the exiled pool only: Diregraf Scavenger, Graveyard Trespasser, Mastermind Plum, Raven Eagle, Deathgorge Scavenger. (f) Becomes-the-target bodies: "counter that spell or ability" (`CounterSpellEffect target_from_trigger_event="stack_id"`, spell or ability item) and "that spell or ability's controller sacrifices a land of their choice" (`player {"of":"event_player"}`), both head-gated by the v688 marker: Glyph Keeper, Jetting Glasskite, Shimmering Glasskite, Lava Runner. Tests (real casts/attacks, picks answered, negative controls): `backend/tests/test_par132_any_number_this_way.py` (18), `test_par132_becomes_target_bodies.py` (4), plus v688's `test_par132_this_way_loops.py` (6). Suite 14,721 passed / 1 skipped (`--full-cache`).
- **Done (v691, +7 / -0 vs v690; 21,819 / 35,046 expected):** (g) "<discard/sacrifice ...>. If a [non]<type> card is discarded this way, <body>" and "<...>. <effect> for each [non]<type> discarded/sacrificed this way" (`segmenter._discarded_this_way_specs`): first-clause `mark_event_log` (window on the source, so it survives the affected player's pending choice; reused rather than a new GameContext pool) + `this_way_pool` condition pools `discarded`/`sacrificed` and amounts `discarded_this_way`/`sacrificed_this_way` (`effect_amounts.discarded_this_way`, over `DISCARD_CARD` / `SACRIFICE` events). Verb must match the first clause. Cards: Lord Windgrace, Civilized Scholar, Psychic Miasma (returns itself from the stack only on a land discard), Seasoned Pyromancer, Gerrard's Verdict, Visions of Ruin, Voracious Fell Beast. Suite 14,733 passed / 1 skipped (`--full-cache`). Hook runs after the any-number pick path and refuses `sacrifice` bodies (a `$n` count is not an int). Tests: `backend/tests/test_par132_discarded_this_way.py` (12, real casts/activations, picks answered, negative controls).
- **In progress:** nothing.
- **Next step:** remaining `this way` tallies: `sacrifice x <noun>` count form (Nahiri's Lithoforming, Gluttonous Hellkite's cast trigger), sacrifice-as-cost windows (Boneyard Desecrator, Thallid Omnivore), subtype conditions (Warren Weirding), total-power/greatest-power/mana-value measurements over the pool (Reign of the Pit, Shadowgrange Archfiend, Ill-Timed Explosion, Reckless Handling needs a search-clause body), tapped/returned pools, additional-cost tallies (Dargo, Explosive Singularity, Burn at the Stake, Devouring Greed/Rage). Or Unsettled Mariner/Parnesse/Rayne/Surrak (`you or a permanent you control becomes the target` heads) and the Kira/Nadu quoted grants.
- **Decisions:** selected by the orchestrator (lowest ID among equal eligible PAR tickets; MEC-125 excluded by user). `run_tests.py` needs `--hard-timeout 1500` (suite now ~210s, default 120s kills it).
- **Baselines / artefacts:** snapshot of v687 at /private/tmp/claude-501/par132_base.json (scratch).
- **Known failures:** none.
- **Residue (re-sized at v690, `parser_probe.py blocked`: `(tapped|sacrificed|returned|discarded|exiled|destroyed|dealt damage|affected) this way` 201 cards / 171 solo, was 221 / 191; `becomes the target of a spell or ability` 19 / 17 solo, was 23 / 21). Items below were sized at v687; items 2 and 4 are partly closed (see Done):**
  1. `for each X, choose up to one target ... that player controls` announce+body: 4 solo (Decoy Gambit, Kitesail Larcenist, Mega Flare, Tolarian Contempt; Shellshock/Disorienting Choice use the `. ... each of those`/`chosen this way` follow-ups) - needs per-round chosen-set referent, not built.
  2. `this way` family: 52 cards for `creature(s) affected/dealt damage/exiled/destroyed/tapped/chosen this way` (41 solo); 77 solo for the broader for-each/destroyed/exiled/sacrificed/tapped/discarded/returned this way regex. Remaining: tapped/sacrificed/discarded/returned tallies (no engine tally yet), `chosen this way`/`those creatures` (382 cards, 313 solo, diffuse), "its controller reveals/searches" per-object bodies (Chaos Mutation, Chaotic Transformation, Indomitable Creativity, From the Ashes), color-qualified counts (Culmination of Studies), "that player investigates for each ..." (Declaration in Stone).
  3. prior-target group bodies (Alpha Brawl, Deputy of Detention, Legions to Ashes): not sized yet.
  4. trigger heads: `beginning of combat on each opponent` 3 solo (Champions of Minas Tirith, Fight or Flight, Web of Inertia: body-blocked: pay-or-cannot-attack, piles); `becomes the target of a spell or ability` 25 cards (23 solo, now ~21) - heads already parse, bodies missing ("counter that spell or ability" + "for the first time each turn" Glyph Keeper cluster, "that spell or ability's controller sacrifices a land", quoted grants Kira/Nadu); `defending player` 156 cards (130 solo), mostly body-side; `from an instant or sorcery` 0.
  5. atomic combat heads: `enters ... attacking` 4 solo; blockers/attached subjects not re-sized.
  6. `that much` 125 (99 solo); `for as long as ~ remains on the battlefield` 16 (15 solo; control-duration cluster); Commando Raid quoted wrapper not sized.
