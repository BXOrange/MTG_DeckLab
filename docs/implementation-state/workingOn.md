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
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PLAY-ALL · Make every saved deck playable

- **Started / last update:** 2026-10-01 / 2026-10-12
- **Goal:** Bring every non-cube saved deck to N/N and fix all recorded correctness gaps (user-confirmed scope); Commander Cube remains optional.
- **Done:** Step 0 (War Room and alternate-name resolution) and Step 1 handler batches; every non-cube saved deck is N/N (see Coverage below) and the earlier correctness gaps are closed. General parser results are in `Done_Backend.md`; card implementations and their limitations live in `game/card_catalogue/` and `tests/game/catalogue/cards/test_*_deck.py`.
- **Delivered:** Shared engine fixes and verified deck corrections are documented in [Done_Backend.md](Done_Backend.md).
- **Next step:** All recorded gameplay correctness gaps and the three integration-coverage gaps are closed. Full backend including full-cache: 12,926 passed. Next: remaining parser axes below; remeasure and synchronize coverage after further parser changes. Commander Cube remains optional.
- **Decisions:** Prioritize shared parser axes, then decks by marginal cost. Reuse existing primitives before adding new ones. Hand-author isolated gaps; Alchemy is a permanent non-goal. Coverage N/N means MODELED or AUTHORED, not proof that every printed ability is rules-exact.
- **Baselines:** PARSER_VERSION 624 (v623 Defilers, v624 pinned dies-this-turn bodies; v622 generic Miracle continuation; retains card copies, filtered choices, any-number targets, sacrifice-count costs, Rooms and RULE 610.3 exile instructions). Full-cache corpus coverage 21,045/35,046 (60.0%); Commander-legal 20,270/32,068 (63.2%), measured 2026-10-12 at v624 and synchronized in CLAUDE.md, PARSER_LONG_TAIL.md and status.de/en.js. Latest validation: full backend including the full-cache tier 12,926 passed (2026-10-12; Windows --timeout=120). Saved decklists are available on this PC; remaining counts below have been remeasured.
- **Known failures:** None — full backend including full-cache: 12,926 passed (2026-10-12). Chromium verified Miracle’s private reveal, public trigger, multiplayer passes and resolution-only cast window, Cane’s immediate paid copy cast and Urianger’s private look/exile sequence without move-log leaks, Reunion’s bounded targets and early finish plus Betor’s independently optional targets with a Multiplayer response window, Disorienting Choice’s announced opponent targets and Primordial Mist’s chosen exile cost with deferred permission, Archangel’s block-cost decline/confirmation with HTTP payment timing, Eliminate’s announced X targets and selected sacrifice costs, Plumb’s optional multi-sacrifice picker and payment timing, Kotis’s three-card exile cost picker, copied countered X spells with rewind, Demonstrate opponent/target choices with rewind, independent copy choices with rewind, the paired sacrifice picker and a library-origin cast through the shared board and HTTP; bundled Node syntax checks passed.

### Residue · cards and remaining deck order

- **Coverage (remeasured 2026-10-12 across all 41 saved decks):** Every non-cube deck is N/N and no names are unresolved, including after a full offline reseed; Turtle Power! remains 93/93. Commander Cube remains optional at 570/749 (179 missing).
- **Batching hint:** the Foundations/Bloomburrow/Tarkir/Aetherdrift/Final Fantasy precons overlap heavily; before each deck, run `--uncovered` and prefer cards shared with other open decks and shared parser axes. Remeasure before ordering further batches.

### Residue · classification of the gaps (2026-10-07)

- **Shipped (ENG-52 / PAR-148):** Adeline's and Vial Smasher's "or a planeswalker they control" choices (`_offer_attack_defenders`, `_request_damage_recipient`); Ainok attacks "that player" only, as printed. Angel of Destiny's end-step loss still counts players attacked directly only.
- **Card fixes with existing primitives (not new mechanics):** auto-picks that should prompt (Espers to Magicite, Collective Effort, Scholar of New Horizons); resolution-time choices that should be announced targets/costs (Sepulchral Primordial).
- **Test-only:** the three integration-coverage gaps below.

**Verified rules clarification:** Herald of Eternal Dawn does not prevent the last remaining opponent winning: RULE 104.2a explicitly overrides cannot-win effects. Regression: `test_last_player_wins_despite_heralds_cannot_win_effect`.

### Residue · known correctness gaps

Coverage completion does not close these recorded limitations; confirm them against the current card files before fixing them.

- **Alternate-name cache persistence:** Verified requested names and printing names are retained independently of the current printing. All 14 previously unresolved saved-deck print names are cached, remain resolvable after a complete offline reseed and resolve case-insensitively after reopening. Cache/loader tests cover a provider response without `flavor_name`, multiple aliases, printing replacement, canonical-name precedence and schema-reset/reseed behavior (50 passing tests). All 41 saved decks were rechecked: all non-cube decks N/N; zero unresolved names. Broad validation: full backend including full-cache, 12,926 passed (2026-10-12; Windows --timeout=120).



- **Death Toll:** Grist has a bound zone-scoped 1/1 Insect creature static, retains its printed/copiable card, and counts only its controller's graveyard for −5. Zone properties, own mill, Reanimate and noncreature spell taxes have passing regressions; the off-battlefield audit is done (hand free-cast filters, graveyard chosen-type/donor pools and the unique-name check read derived creature status; one hand-filter regression). Into the Pit requires distinct permission and printed sacrifice payments, including counted sacrifices; four focused regressions pass. Winter permits completing only legal four-type sets, with explicit cancellation; three focused regressions pass. Broad validation: full backend including full-cache, 12,926 passed (2026-10-12).
- **Verified deck corrections:** Shorikai uses current source mana value (including announced X) and Calendar triggers only on actual untaps. Kardur creates a dynamic combat-rule requirement, not goad; later arrivals, source departure, player selection and next-turn expiry are tested. Dack prepares entry choices before simultaneous entry, with mutual ETB detection tested. Angel of Destiny already uses DAMAGE `target_id`; direct-player-only loss is correct under RULE 508.1b/508.3e, verified against real planeswalker/battle attacks. Broad validation: full backend including full-cache, 12,926 passed (2026-10-12).

- **Revival Trance:** All 50 deck tests pass. Espers uses a separate optional reflexive target restricted to its actual exile batch; selection, decline and broken exile incarnations are tested. Rejoin's deferred distinct selections and simultaneous return are tested. Snort's APNAP decisions, post-draw damage and suspended Miracle continuation are tested. Sepulchral Primordial announces optional per-opponent targets before responses and skips removed targets. Broad validation: full backend including full-cache, 12,926 passed (2026-10-12).

- **Multiverse Reforged:** All 58 deck tests pass. Omnath retains restricted mana as colorless without removing restrictions/provenance. Serra offers all card types including Kindred; Emissary and Reproach exclude protected player targets. Proteus Staff prepares entry choices before owner-chosen bottom ordering. Jhoira's printed random order is correct; legendary nonpermanents are skipped. Jace's live control-scoped restriction includes later Jaces as RULE 611.2c requires; its payment prompt can use untapped mana sources via the shared planner (RULE 117.12b). Broad validation: full backend including full-cache, 12,926 passed (2026-10-12).

- **Counter Blitz:** Collective Effort announces distinct Escalate tap choices through the session API and the shared board after targets. Three backend regressions and a Chromium test with actual HTTP/GameSession payment pass, including freely choosing two creatures and excluding duplicates. Scholar of New Horizons offers the optional Plains destination.

- **Limit Break:** All recorded card corrections are implemented. Meteor reads actual exile cast origin and gathers free controller selections per opponent before simultaneous destruction. Hojo reads announced own-creature targets, locks the cost before sacrifices and draws only for activated abilities. Lifestream's Blessing captures greatest creature power at cast time and uses actual exile origin; an uncast copy has no cast-time reading. Yuffie's duration ends permanently on losing control. All 49 deck tests plus cost/condition/copy/mana-planning regressions pass (337 combined); 466 continuation tests also passed. The vocabulary audit now includes real structured condition producers. Broad validation: full backend including full-cache, 12,926 passed (2026-10-12).

### Residue · follow-ups outside individual card coverage

These were recorded as unticketed follow-ups; inspect existing backlog entries before creating duplicates.

- Parser axes: Defilers' permanent-spell filter shipped (v623, Faith/Flesh/Instinct); "when it/that creature dies this turn" now accepts "it" and bodies naming the dying creature's controller, and a bare "return it" returns the dead creature (v624, Virulent Wound). Still open: remaining dies-this-turn bodies (Burn Away, Searing Blood "the creature's controller", Reincarnation, Rushed Rebirth, Fatal Fissure earthbend, Sandals/Initiate "~" bodies, Time to Feed), broader mana-ability counter riders, counter/pump-then-fight, flicker with riders, multi-event attack/block/target heads, equipped-creature X pump.
- Integration coverage gaps closed: Patrolling Peacemaker (real opposing Bolt), Kellan (real flashback cast), Giggling Skitterspike (BLOCKS).
