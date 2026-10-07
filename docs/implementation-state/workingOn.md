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

Block template (copy below the line, fill in):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** None — full backend including full-cache: 12,650 passed (2026-10-07). The shared board passed the bundled Node syntax check; Chromium verified both paired sacrifice picks through HTTP against an isolated test game.

---

## PLAY-ALL · Make every saved deck playable

- **Started / last update:** 2026-10-01 / 2026-10-07
- **Goal:** Bring every non-cube saved deck to N/N and fix all recorded correctness gaps (user-confirmed scope); Commander Cube remains optional.
- **Done:** Step 0 (War Room and alternate-name resolution) and Step 1 handler batches; every non-cube saved deck is N/N (see Coverage below) and the earlier correctness gaps are closed. General parser results are in `Done_Backend.md`; card implementations and their limitations live in `game/card_catalogue/` and `tests/game/catalogue/cards/test_*_deck.py`.
- **Delivered:** Sin/Dermotaxi before-entry choices; Rooms with two independent doors (MEC-111); immediate exile-until-departure returns with incarnation tracking (MEC-113). Paired sacrifice choices, restricted Equip flags, per-card graveyard exits, damage-batch subjects and death-copy/return incarnation capture are also verified. See the implementations and regression tests; shared mechanics are documented in `Done_Backend.md`.
- **Next step:** Close the remaining per-card correctness gaps below using existing primitives; add the shared new-target choice mechanism (MEC-112). Commander Cube remains optional.
- **Decisions:** Prioritize shared parser axes, then decks by marginal cost. Reuse existing primitives before adding new ones. Hand-author isolated gaps; Alchemy is a permanent non-goal. Coverage N/N means MODELED or AUTHORED, not proof that every printed ability is rules-exact.
- **Baselines:** PARSER_VERSION 618 (Rooms grammar and RULE 610.3 exile instructions). Full-cache corpus coverage 20,372/35,046 (58.1%), measured 2026-10-04 at v604 (not re-measured). Latest validation (2026-10-07): full backend including the full-cache tier 12,650 passed. Saved decklists are available on this PC; remaining counts below have been remeasured.
- **Known failures:** None — standard tier 12,194 passed / 335 skipped and full-cache tier 12,529 passed on 2026-10-07 (final tree). The phenomenon regression now uses inert departure/destination planes to isolate the encounter trigger from random catalogue effects. Frontend lint remains unverified because Node/npm is unavailable; the changed choice renderer passed V8 syntax/render checks.

### Residue · cards and remaining deck order

- **Coverage (remeasured 2026-10-06 across all saved decks; no unresolved cards):** Every non-cube deck is N/N, including Turtle Power! 93/93. Commander Cube remains optional at 569/749 (180 missing).
- **Batching hint:** the Foundations/Bloomburrow/Tarkir/Aetherdrift/Final Fantasy precons overlap heavily; before each deck, run `--uncovered` and prefer cards shared with other open decks and shared parser axes. Remeasure before ordering further batches.

### Residue · classification of the gaps (2026-10-07)

- **Missing mechanics (own ticket, `BACKLOG.md`):** MEC-112 copy new-target choice (RULE 707.10c).
- **Shipped (ENG-52 / PAR-148):** Adeline's and Vial Smasher's "or a planeswalker they control" choices (`_offer_attack_defenders`, `_request_damage_recipient`); Ainok attacks "that player" only, as printed. Angel of Destiny's end-step loss still counts players attacked directly only.
- **Card fixes with existing primitives (not new mechanics):** auto-picks that should prompt (Kotis, Espers to Magicite, Collective Effort, Scholar of New Horizons, Plumb the Forbidden); resolution-time choices that should be announced targets/costs (Eliminate the Competition, Immoral Bargain, Disorienting Choice, Reunion of the House, Betor, Sepulchral Primordial, Primordial Mist); turn-long windows that should use `play_resolution_card` RULE 608.2g (Ur-Sphinx, Aetherworks Marvel, Kefka, Strago, Valigarmanda); Archangel of Tithes block-tax decline.
- **Replay-only / test-only:** Serra Avenger's round floor, Steward of the Harvest and the three integration-coverage gaps below.

**Verified rules clarification:** Herald of Eternal Dawn does not prevent the last remaining opponent winning: RULE 104.2a explicitly overrides cannot-win effects. Regression: `test_last_player_wins_despite_heralds_cannot_win_effect`.

### Residue · known correctness gaps

Coverage completion does not close these recorded limitations; confirm them against the current card files before fixing them.

- **SpongeBob:** Gogo's copied abilities retain targets (→ MEC-112).
- **Sultai Arisen:** Kotis auto-picks the three other graveyard cards it exiles (oldest first, no prompt); Steward of the Harvest borrows mana abilities through the existing borrow machinery, not tested against non-basic activated land abilities beyond Command Tower's.
- **Mardu Surge:** Eliminate the Competition (and Immoral Bargain) sacrifice and choose the X creatures at resolution, not as announced cost and targets; Kaya's +1 counter target and Windbrisk's attack count use the existing selectors without a planeswalker-attack special case; Plumb the Forbidden still pays its optional sacrifice at resolution and models copies as scaled draw/life loss; its sacrifice count now uses the actual picks, including tokens.
- **Calling All Angels:** Archangel of Tithes' block tax is auto-paid at `declare_blockers` (an unaffordable block is rejected, there is no explicit decline); Serra Avenger's turn count in a Replay board is floored at the round number;
- **Jump Scare!:** Disorienting Choice chooses its permanents on resolution (not as targets), so hexproof/protection do not stop it; Primordial Mist exiles on resolution rather than as a paid cost (it can be responded to);
- **Abzan Armor:** Reunion of the House chooses on resolution rather than announcing its printed targets; Betor's two targeted halves are two end-step triggers.

- **Living Energy:** Aetherworks Marvel's `look_top_cast_free` takes the six cards out of the library for the choice (cast from exile, not from the library).
- **Scions & Spellcraft:** Blue Mage's Cane lets you cast the exiled card itself (not a copy) for {3}, from any opponent's graveyard rather than only the defending player's; Summon: Good King Mog XII targets the token it copies (``token_you_control``) instead of choosing untargeted; Urianger Augurelt exiles the top card face down without a separate look; Estinien counts dealers found in any zone;
- **Miracle Worker:** Aminatou's granted Miracle uses the engine's whole-turn miracle window.

- **Death Toll:** Grist's "isn't on the battlefield, it's an Insect creature" is not a characteristic effect off the battlefield (milling Grist counts as an Insect via `milled_subtype_this_way` ``name: source``, a Grist in your graveyard adds to the −5 via `cards_named_source_in_all_graveyards`); Into the Pit's top-of-library sacrifice is not forced distinct from a spell's own sacrifice cost; Winter selects the graveyard set first and judges it once (a set with fewer than four types does nothing).
- **Shorikai Vehicles:** Rebbec protects by the source's printed mana value (``mv:N`` qualities); The Millennium Calendar's trigger fires on every untap step (untapping nothing adds zero counters).
- **Endless Punishment:** Kardur's goad marks the creatures present as it resolves (later arrivals are not forced);
- **Hope to the last:** Angel of Destiny's end-step loss counts only players attacked directly (not planeswalkers/battles), and its "that player" life gain needs the DAMAGE event's ``target_id``.

- **Sans Soleil MWI:** Dack Fayden, Helping Hand puts creatures onto the battlefield through sequential entry chooser calls rather than one simultaneous entry batch.

- **Revival Trance:** Espers to Magicite auto-copies the highest-mana-value creature rather than a reflexive optional target; Sepulchral Primordial chooses at resolution rather than as trigger targets; Rejoin the Fight returns picks as each opponent answers rather than after every pick. Snort asks the controller first and damages each accepting opponent after their own draw. Kefka uses a turn-long free-cast window (including non-instants in the end step), with owner life loss per cast. Strago uses the same-turn window, turn-scoped haste and a one-shot end-step sacrifice. Valigarmanda's chapter I takes the newest matching card per graveyard, and chapters II–IV grant turn-long permissions for all linked spells rather than a single during-resolution cast. Card-specific limitations are documented in the card modules and their effects.

- **Multiverse Reforged:** Omnath converts only unrestricted mana; Serra's Emissary does not offer Kindred and protects a player from damage only; Teferi's Reproach's player shield covers damage and life changes, not targeting; Proteus Staff and Jhoira put the rest on the bottom in random order (no owner-chosen order); Venser's spell copies keep the original's targets (→ MEC-112); The Ur-Sphinx's free-cast window lasts the turn (not only during resolution) and lands are not castable; Jace's attack bar covers every Jace the controller owns, and the opponent's {2} uses the generic pay-or prompt.

- **Counter Blitz:** Collective Effort's Escalate creatures are chosen automatically (lowest power); Scholar of New Horizons always puts the Plains onto the battlefield when an opponent controls more lands.

- **Limit Break:** Professor Hojo reads "creature you control" off the ability's target kinds and counts triggered abilities too; Foretell cards read "cast from exile" as `foretold` (Lifestream's Blessing measures X at resolution; Ultimate Magic: Meteor picks the greatest-mana-value artifact or land per opponent); Yuffie's control lasts while Yuffie stays on the battlefield;

### Residue · follow-ups outside individual card coverage

These were recorded as unticketed follow-ups; inspect existing backlog entries before creating duplicates.

- Add parser axes for Defilers' permanent-spell filter, broader mana-ability counter riders (one counter on the source is supported), counter/pump-then-fight, flicker with riders, multi-event attack/block/target heads, equipped-creature X pump, and Turn Inside Out's temporary dies trigger.
- Integration coverage still limited for Patrolling Peacemaker (event fired by hand), Kellan (no real graveyard cast), and Giggling Skitterspike (BLOCKS not exercised in its deck test).
