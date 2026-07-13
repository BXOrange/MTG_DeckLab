# Completion Roadmap

The single, dependency-ordered plan for finishing the implementation. It
consolidates the granular backlogs and the design docs into milestones you
can execute in order.

**Live sources this reconciles**

- Granular open items: [`backend/ToDo_Backend.md`](../../backend/ToDo_Backend.md),
  [`frontend/ToDo_Frontend.md`](../../frontend/ToDo_Frontend.md)
- Shipped: [`Done_Backend.md`](Done_Backend.md),
  [`Done_Frontend.md`](Done_Frontend.md)
- User-facing coverage: in-app **Engine-Status** tab
  (`../../frontend/src/js/implementationStatusView.js`)
- Oracle parser design: [`09_ORACLE_EFFECT_PARSER.md`](../concepts/09_ORACLE_EFFECT_PARSER.md)
- Rule lookups: [`Reference/rules_wiki/`](../Reference/rules_wiki/) (`RULE <n>` → CR line)
- Archived Weeks 1–4 roadmap: [`history/IMPLEMENTATION_STATUS.md`](history/IMPLEMENTATION_STATUS.md)

---

## Where we are

The **rules-engine core is built** and green (781 backend tests): full
turn/stack/SBA loop, London mulligan, targeting, the complete mana model,
all common combat/evasion keywords (incl. landwalk), the RULE 613 layer
system essentially in full (layers 1 partial/2/4/5/6/7a–e, timestamp-ordered
within a layer, plus cost adjustment), activated/triggered/static abilities
with cost parsing (incl. loyalty `[±N]`), replacement effects, a growing set
of one-shot effects, interactive trigger ordering and per-trigger target
choice, commander damage + commander tax, planeswalker loyalty abilities,
Aura/Equipment/Fortify/Reconfigure attachment, conditional enters-tapped
lands, basic card structures (DFC transform, MDFC back-face casting, token
copies, `become_copy`, Saga lore counters), and a basic interactive priority
primitive. M3 and M4 below (layer system, permanent subsystems) are
**done** in all but two deliberately-deferred corners (layer 3 text-changing,
full 613.8 dependency ordering — see M3).

The dominant remaining gap is still that **card text does not yet fully
become behaviour**: a spell/ability only does something if its card is in
the hand-authored `game/ability_catalogue.py` **or** the oracle-text parser
(`parser/oracle/`) recognizes its clause shape as `MODELED`. The parser
already covers a good chunk of common instants/sorceries/ETB-triggers/
activated/static-anthem shapes; several effect families (regenerate, modal
"choose one"/"up to N" targets) and most parametric-keyword *behaviour*
(kicker/escape alt-costs, annihilator/afflict combat maths) are still open.
That's why the oracle parser is still Milestone 1, now joined by M5
(multiplayer/priority wiring) as the other big remaining lift — everything
else is comparatively narrow, additive work.

---

## Comprehensive-Rules coverage at a glance

| CR area | State | Notes |
| --- | --- | --- |
| 100–123 Game concepts | ✅ mostly | mana, life, damage, counters, targets, costs, timing (solo + basic interactive priority), tokens. Emblems (114), Stickers (123) not modeled. |
| 200–213 Parts of a card | ✅ mostly | Card model complete, loyalty tracked and playable. Defense (210)/Battles not. |
| 300–315 Card types | ◐ | artifact/creature/enchant/instant/land/sorcery/planeswalker done, incl. Aura/Equip/Fortify/Reconfigure attachment. Battles/dungeons/adventure/split not; Saga/DFC partial (see 700–733). |
| 400–408 Zones | ✅ | battlefield/stack/hand/library/graveyard/exile/command all present. |
| 500–514 Turn structure | ✅ | complete, walked from a sequence with skip effects. |
| 600–616 Spells/abilities/effects | ◐ | casting/activated/triggered/static/mana/replacement/loyalty (606) done; layers (613) done except layer 3 + full dependency ordering (deliberately deferred, see M3); replacement/prevention ordering (616.1) still deterministic, not player-chosen. |
| 700–733 Additional | ◐ | SBAs (704) done; keyword abilities (702) recognized + bound (flag + landwalk); keyword *actions* (701) partial via effects. Copying (707): token copies + `become_copy` done, not a true layer-1 continuous effect. DFC transform (712.3–9) + MDFC back-face cast (712.10) done; Saga (714) lore-counter mechanics done, chapter *abilities* not; Adventure (715)/Split-Fuse (709)/Class (716)/Leveler (711)/Day-Night (731)/Monarch/Initiative not. |
| 800–811 Multiplayer | ✖ | interactive `pass_priority(player)` primitive built; `create_multiplayer` still raises, route returns 501. |
| 900–905 Casual variants | ◐ | Commander (903) damage + command zone + tax (903.8) done. Others not. |

---

## Milestones (execute in order)

Each milestone lists its goal, the concrete work, what it unblocks, and the
reference. Frontend UI work is called out per milestone; it can proceed in
parallel once the backend seam exists.

### M1 — Oracle-effect parser (keystone, in progress)
**Goal:** arbitrary `oracle_text` → `AbilitySpec` IR → `GameEffect`, so
spells/abilities resolve without a hand-authored catalogue entry.
Follows [`09_ORACLE_EFFECT_PARSER.md`](../concepts/09_ORACLE_EFFECT_PARSER.md). Phase 0
(IR + binder + one card) and the Phase 1 *keyword* catalogue are **done**.

- ✅ Normalizer + segmenter (`parser/oracle/normalize.py`, `segmenter.py`):
  split abilities on newlines, peel trigger wrapper → `EventType`, "you may"
  → optional, chain effect clauses.
- ✅ Deterministic effect-family handler table (`catalogue/handlers.py`) for
  damage/draw/discard/destroy/gain_life/counter/mill/exile/tap/±1/±1 counters/
  **pump/scry**/token creation, with shared TARGET/NUMBER/COUNT sub-grammars
  (`catalogue/subgrammars.py`). Tokens carry the full RULE 704.5d cease-to-exist
  lifecycle (`GameObject.is_token`, `RulesEngine.create_token`/
  `_remove_stranded_tokens`). *(search stays catalogue-authored — a later family.)*
- ✅ Fail-closed full-span **coverage gate** (`gate.py` `parse_oracle` →
  `MODELED`/`UNMODELED` + unclaimed-clause list). Wired into
  `ability_catalogue.specs_for` (unregistered + `MODELED` only). Tests in
  `test_oracle_pipeline.py`.
- ✅ **Activated-ability** clause parsing (`<cost>: <effect>` → `costs.py` +
  the handler table; mana abilities recognised, loyalty deferred to M4 —
  which itself is now done).
- ✅ Deduped, template-abstracted **processing list** + cache-wide coverage
  metric (`processing_list.py` `coverage_report`/`coverage_over_cards`).
- ✅ **Static/anthem clause** handler (`catalogue/static_handlers.py`): plain,
  tribal lords, token anthems, colour-scoped ("Black creatures …", Bad Moon),
  **global** (no "you control"), and compound "get +N/+N and have [kw]" — with
  subtype/token/color/exclude_self selectors in `continuous.affected_objects`.
- ✅ **Replacement clause binding** (the binder side): a hand-authored/parsed
  `replacement` spec builds a `ReplacementEffect` via `ReplacementRegistry`
  (`prevent_damage` shipped). Oracle-text *recognition* of replacement
  clauses (a target/duration grammar for the front-end) is still open.
- ⏳ Remaining: more effect families (**regenerate**, mode "choose one", "up
  to N" targets — each needs a one-shot `GameEffect` + registry entry
  first); parse-on-load memoization in `LazyCardLoader` (bind-per-game
  already wired).
- **Unblocks:** plain instants/sorceries/ETB-triggers/activated/static
  abilities from the handled families already resolve with no catalogue
  entry; is the seam M2 plugs into. *(docs/09 Phases 1–2.)*

### M2 — Parametric keyword binding (open)
**Goal:** give behaviour to keywords already parsed-but-inert.

- Landwalk is **done** (fully bound into combat, RULE 702.14) — the first
  parametric keyword to go all the way from parse → parameter → behaviour.
- Still open: alternative/additional-cost keywords (kicker, multikicker,
  buyback, escape, flashback…) via the cost system + cast-time choices;
  combat-math keywords (annihilator N, afflict, bushido, rampage…);
  protection *quality*, ward, hexproof-from as targeting/replacement
  filters. Each parameter already binds onto
  `GameObject.parametric_keywords` — nothing yet *consumes* it except
  landwalk.
- **Depends on:** M1 keyword catalogue (done) + cost/targeting systems (done).
- Backlog: `ToDo_Backend.md` "Rules Engine … parser" progress note.

### M3 — Layer system completion (RULE 613) — done, two corners deliberately deferred
**Goal:** finish `game/continuous.py` to the full layer set.

- ✅ Layers 2 (control), 4 (type), 5 (colour), 6 (ability-adding — incl.
  granting a non-keyword mana/triggered ability, not just a keyword slug),
  7a (CDA), 7b–d (set/counters/pump), 7e (P/T switch) — all bridged by the
  `StaticAbility`/`EffectRegistry`, timestamp-ordered within a layer.
- ◐ Layer 1 (copy effects, RULE 707): `become_copy` mutates the object in
  place rather than running as a per-recompute layer-1 pass; see M6.
- ✖ **Deliberately not built** (evaluated 2026-07-09, audited the full
  ~1000-card cache): literal **layer 3** (RULE 612 text-changing, e.g.
  Artificial Evolution) — zero cards in the cache need it, nothing to
  build or test against. Full **RULE 613.8 dependency ordering** — every
  real interaction in the current effect vocabulary crosses *different*
  layers, already sequenced correctly by the fixed layer order; no same-layer
  dependency case exists to construct one against. Revisit both if a
  card/effect ever needs them.
- **Depends on:** layer 1 overlaps with M6 copying.

### M4 — Permanent subsystems — done
**Goal:** the four independent, medium-sized permanent mechanics below.
All four are **done**:

- ✅ **Loyalty / planeswalker abilities (606):** loyalty-cost kind in
  `costs.py`, sorcery-speed + once-per-turn gate, `[+N]/[-N]/[0]`
  activation, 0-loyalty SBA (704.5i), planeswalker damage marking. *UI:*
  still open — clickable loyalty controls (`ToDo_Frontend.md`).
- ✅ **Aura / Equipment attachment (303 / 301.5 / 702.6/67/151):** Aura ETB
  attaches to target (303.4f); equip/fortify/reconfigure as sorcery-speed
  activated abilities; `continuous.recompute` reads `attached_to` into
  layers 6/7 (`affects="attached_permanent"`). Remaining sliver:
  re-validating an *existing* attachment's legality every SBA pass (today
  only "host left the battlefield" is checked). *UI:* still open — cast
  target for Auras, "Ausrüsten" control (`ToDo_Frontend.md`).
- ✅ **Commander tax (903.8):** per-commander from-command-zone cast counter
  on the player, read by the cost calc, carried by rewind snapshots.
- ✅ **Conditional enters-tapped (614.1):** shock/check/fast/slow lands — a
  replacement-effect + player choice (pay life) or deterministic board
  evaluation instead of a plain boolean. *UI:* still open — pay-2-life
  prompt (`ToDo_Frontend.md`).

### M5 — Interactive priority, multiplayer & ordering choices (in progress)
**Goal:** two humans can hold priority and respond.

- ✅ Interactive priority **primitive**: `GameEngine.pass_priority(player)`
  (RULE 117.3-4) resolves the stack only once every living player has
  passed in succession, otherwise advances APNAP; any real action reclaims
  priority. Solo/goldfish auto-resolve is unchanged when called with no
  player.
- ✅ Player-made **ordering choices**: triggers within a controller (603.3b,
  opt-in `interactive_ordering`) and a triggered ability's own target/"you
  may" choice (115/603.3c/603.5) are both interactive. Known narrow gap:
  the two together (a targeted trigger placed via the manual-ordering path)
  isn't handled.
- ⏳ Still open: wire `WebSocket /ws/game/{id}` into a server-held session
  (run the action through the engine, broadcast `GameState.to_dict()`);
  remove the `create_multiplayer` stub; interactive **blocker declaration**
  UI (engine-ready via `declare_blockers`, no opponent-side UI yet);
  replacement/prevention ordering by the affected player (616.1, still
  deterministic).
- **UI:** opponent zones, hidden opponent hand, turn/priority indicator,
  per-creature attacker subset selection, slow-opponent timeout — all still
  open (`ToDo_Frontend.md` "Multiplayer").

### M6 — Card-type structures (partial)
Each is a `type_line`/layout the parser or a dedicated handler must own; most
depend on M1, and copies feed M3's layer 1.

- ✅ Double-faced transform on the battlefield (712.3–9, `GameObject.transform`)
  and **MDFC back-face casting/playing from hand (712.10)** — both faces
  offered as independent actions, rejected back-face cast rolls back.
  Remaining: a transform *trigger/effect* to call `transform()`, Day/Night
  (731), MDFC commanders cast from the command zone (known deliberate gap).
- ✅ Saga (714) lore-counter mechanics (enter with one, +1 after draw step,
  sacrifice at final chapter). Remaining: the chapter *abilities* firing per
  counter. Class (716)/Leveler (711) not started.
- ✅ Copying objects (707): token copies (`copy_permanent`) and "becomes a
  copy of" (`become_copy`, modeled as an ordinary ETB trigger rather than
  true 614.1c/614.12 replacement timing) are both done and interactively
  playable. Remaining: the true layer-1 continuous-effect version (M3).
- Adventure (715) & Split/Fuse (709): recognised structurally
  (`Card.is_adventure`/`is_split`) but still resolve as the single
  front-face spell — not started.
- Battles (310), Dungeons (309) — not started.
- Deprioritized until a deck needs one: Emblems (114), Stickers (123), Monarch
  (725) / Initiative (726), Rad counters (728), remaining multiplayer/casual
  variants.

### M7 — Product features (parallel track, not rules-engine)

- **Deck analysis (UC2):** the **static/heuristic half is done** —
  mana curve, type distribution, land archetypes, Command Zone categories,
  and a WotC-Commander-Brackets-style heuristic all ship client-side, no
  backend call (`Done_Frontend.md` "Deck analysis (UC2)"). Still
  open: the **LLM-backed** narrative half — `POST /api/decks/{id}/analyze`
  (Claude API, prompt templates, structured output, caching; design the
  `Analysis` model alongside — the reserved `Deck.analysis_id` shape isn't
  final). *UI:* analyze button + narrative results view + cache indicator,
  additive to the existing static/Bracket sub-tabs. Use the latest Claude
  models.
- **Auth & persistence:** accounts/login, scope saved decks to an owner, game
  history/session persistence. *UI:* login/signup, token storage, reconnect.
- **Bot AI (UC5):** upgrade the greedy `run_goldfish_turn` to weigh lines.
  *UI:* bot-vs-manual selector, action visualization + speed control.
- ✅ **External deck-builder import:** Moxfield tried twice (client-side,
  then a server-side proxy) and reverted both times — confirmed via a
  live test against a real deck id that Cloudflare genuinely blocks it
  (not just a CORS/header issue), so it'd need a headless-browser
  fallback or residential-IP proxy to actually work (backend ToDo
  "Import — follow-up from the frontend"). Archidekt's API has no such
  block (plain unauthenticated request → real deck JSON) — shipped as
  its own "Import Deck" sidebar tab (`Done_Backend.md`/`Done_Frontend.md`
  "Import").

---

## Suggested sequencing

```
M1 (oracle parser) ──┬─▶ M2 (parametric keyword behaviour)
                     └─▶ M6 remainder (Adventure/Split, Battles/Dungeons)
M3 (layers)          ── done except two deliberately-deferred corners
M4 (permanent subsystems) ── done (engine-side); UI hookups remain in ToDo_Frontend.md
M5 (priority/multiplayer) ── primitive + ordering choices done; session/WS wiring + blocker UI remain
M7 (product: LLM analysis / auth / bot) ── parallel track, no rules-engine dependency;
                                             static deck analysis already shipped
```

**Critical path to "most decks are playable solo":** M1 → M2. Full
two-player play additionally needs the rest of M5. Everything in the
remainder of M6/M7 is additive.
