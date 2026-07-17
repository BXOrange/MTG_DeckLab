# Completion Roadmap

The single, dependency-ordered plan for finishing the implementation. It
consolidates the granular backlogs and the design docs into milestones you
can execute in order.

## Live sources this reconciles

- Granular open items: [`backend/ToDo_Backend.md`](../../backend/ToDo_Backend.md),
  [`frontend/ToDo_Frontend.md`](../../frontend/ToDo_Frontend.md)
- Shipped: [`Done_Backend.md`](Done_Backend.md),
  [`Done_Frontend.md`](Done_Frontend.md)
- User-facing coverage: in-app **Engine-Status** tab
  (`../../frontend/src/js/implementationStatusView.js`)
- Oracle parser design: [`09_ORACLE_EFFECT_PARSER.md`](../concepts/09_ORACLE_EFFECT_PARSER.md)
- Rule lookups: [`Reference/rules_wiki/`](../Reference/rules_wiki/) (`RULE <n>` → CR line)

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
| 600–616 Spells/abilities/effects | ◐ | casting/activated/triggered/static/mana/replacement/loyalty (606) done; layers (613) done except layer 3 + full dependency ordering (deliberately deferred, see M3); replacement/prevention ordering (616.1e/f) is interactive, by the affected player. |
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
Follows [`09_ORACLE_EFFECT_PARSER.md`](../concepts/09_ORACLE_EFFECT_PARSER.md).

- Phase 0 (IR + binder + one card) and the Phase 1 *keyword* catalogue are **done**.
- ⏳ **Remaining, priority-ordered by real cards-unlocked** (verified
  2026-07-16 by running `processing_list.coverage_over_cards()` over the
  live cache — 21.4% of 2,869 cards fully `MODELED`; **re-run this before
  trusting the counts below**, the cache keeps growing and the ranking
  shifts):
  1. A real "up to two/three/N"/"up to X" **multi**-target choice (N>=2,
     see Batch 11 above for why it's a separate, larger feature from the
     N=1 case just shipped), a "remove a counter from ~" activation-cost
     shape (`costs.py` — newly surfaced by an earlier batch's real-card
     debugging, blocks Crystalline Crawler/Mana Bloom/Walking Ballista/
     Triskelion/Wishclaw Talisman/Transmogrifying Wand — plausibly the
     next highest-leverage single fix, not yet template-ranked), a
     life-total-scaled amount ("lose life equal to that card's mana
     value" — Reanimate/Rise from the Grave/Kenrith, newly surfaced by
     an earlier batch, blocks otherwise-complete graveyard-recursion
     cards), the remaining RULE 616.1 replacement-clause formulations
     (`prevent_damage`'s one-shot-spell shape, differently-scoped/
     compound-filter variants — see Batch 11), a kicked spell's "if
     kicked, ... instead" *override* shape (as opposed to the additional-
     effect shape Batch 11 covers), and the processing-list tail — "choose
     \<n\> —"/"choose \<n\> or more —" (fixed and variable multi-*mode*
     selection, RULE 700.2) is now done; remaining top blockers per the
     (stale) live ranking: "you may look at the top card of your library
     any time" (13, a standing *permission* rather than a one-shot/
     triggered effect — no existing family shape to reuse),
     monarch/initiative (7-9 each, deferred per M6), cost-modification
     statics, and emblems.
  2. **Related, same pipeline, separately tracked in `ToDo_Backend.md`**:
    the mana-ability follow-up list from the 2026-07-15 Elf-mana-dork pass
    is now fully done (spend restrictions, Leveler-gating, Deathrite
    Shaman, "any combination of colors", and hand-zone activation) — not
    cache-coverage-ranked since mana abilities are recognized without
    needing a `MODELED` spec.
- **Unblocks:** plain instants/sorceries/ETB-triggers/activated/static
  abilities from the handled families already resolve with no catalogue
  entry; is the seam M2 plugs into. *(docs/09 Phases 1–2.)*

### M2 — Parametric keyword binding — done

**Goal:** give behaviour to keywords already parsed-but-inert.

- Landwalk is **done**
- **Annihilator/afflict/bushido and hexproof are done**
- **Ward is done**
- **Alternative/additional-cost keywords are done**
- **Rampage is done**
- Remaining narrow rough edges, not new features: protection *quality*
  (already fully working via a separate, older path —
  `combat.is_protected_from` — not `parametric_keywords` at all); and
  hexproof-*from*'s quality (currently aliased onto plain hexproof, losing
  the "from X" scope) — see `ToDo_EdgeCases.md`. (A ward cost's own `{X}`,
  RULE 702.21b, is now resolved at the ward ability's resolution time —
  `costs.ActivationCost.x_selector`/`RulesEngine.resolve_ward_effect`.)
  Every parametric keyword
  this engine models now binds onto `GameObject.parametric_keywords` *and*
  consumes it: landwalk/annihilator/afflict/bushido/ward/rampage/kicker/
  buyback/escape/flashback.
- **Depends on:** M1 keyword catalogue (done) + cost/targeting systems (done).

### M3 — Layer system completion (RULE 613) — done, narrowly scoped in two corners

**Goal:** finish `game/continuous.py` to the full layer set.

- ◐ Layer 1 (copy effects, RULE 707): `become_copy` mutates the object in
  place rather than running as a per-recompute layer-1 pass; see M6.
- **Depends on:** layer 1 overlaps with M6 copying.

### M4 — Permanent subsystems — done

**Goal:** the four independent, medium-sized permanent mechanics below.
All four are **done**

### M5 — Interactive priority, multiplayer & ordering choices (in progress)

**Goal:** two humans can hold priority and respond.

- ⏳ Still open: wire `WebSocket /ws/game/{id}` into a server-held session
  (run the action through the engine, broadcast `GameState.to_dict()`);
  remove the `create_multiplayer` stub; interactive **blocker declaration**
  UI (engine-ready via `declare_blockers`, no opponent-side UI yet).
- **UI:** opponent zones, hidden opponent hand, turn/priority indicator,
  per-creature attacker subset selection, slow-opponent timeout — all still
  open (`ToDo_Frontend.md` "Multiplayer").

### M6 — Card-type structures (partial)

Each is a `type_line`/layout the parser or a dedicated handler must own; most
depend on M1, and copies feed M3's layer 1.

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

---

## Suggested sequencing

```code
M1 (oracle parser) ──┬─▶ M2 (parametric keyword behaviour) ── done
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
