# Completion Roadmap

The single, dependency-ordered plan for finishing the implementation. It
consolidates the granular backlogs and the design docs into milestones you
can execute in order.

**Live sources this reconciles**
- Granular open items: [`../backend/ToDo_Backend.md`](../backend/ToDo_Backend.md),
  [`../frontend/ToDo_Frontend.md`](../frontend/ToDo_Frontend.md)
- Shipped: [`../backend/Done_Backend.md`](../backend/Done_Backend.md),
  [`../frontend/Done_Frontend.md`](../frontend/Done_Frontend.md)
- User-facing coverage: in-app **Engine-Status** tab
  (`../frontend/src/js/implementationStatusView.js`)
- Oracle parser design: [`09_ORACLE_EFFECT_PARSER.md`](09_ORACLE_EFFECT_PARSER.md)
- Rule lookups: [`../Reference/rules_wiki/`](../Reference/rules_wiki/) (`RULE <n>` → CR line)
- Archived Weeks 1–4 roadmap: [`history/IMPLEMENTATION_STATUS.md`](history/IMPLEMENTATION_STATUS.md)

---

## Where we are

The **rules-engine core is built** and green (547 backend tests): full
turn/stack/SBA loop, London mulligan, targeting, the complete mana model,
all common combat/evasion keywords, the RULE 613 layer engine (layers
4/6/7b–d), activated/triggered/static abilities with cost parsing,
replacement effects, one-shot effects, commander damage, and the RULE 702
keyword *catalogue* (all 194 keywords parsed; flag keywords bind).

The dominant remaining gap is that **card text does not yet become
behaviour**: a spell/ability only does something if its card is in the
hand-authored `game/ability_catalogue.py`. Everything downstream — most
spells resolving, parametric keywords, several card types — is gated on the
oracle-effect parser. That's why it is Milestone 1.

---

## Comprehensive-Rules coverage at a glance

| CR area | State | Notes |
| --- | --- | --- |
| 100–123 Game concepts | ✅ mostly | mana, life, damage, counters, targets, costs, timing (solo priority), tokens. Emblems (114), Stickers (123) not modeled. |
| 200–213 Parts of a card | ✅ mostly | Card model complete. Loyalty (209) is a value only; Defense (210)/Battles not. |
| 300–315 Card types | ◐ | artifact/creature/enchant/instant/land/sorcery + planeswalker-as-target done. Auras/Equip attach, planeswalker abilities, battles/dungeons/DFC/saga/adventure not. |
| 400–408 Zones | ✅ | battlefield/stack/hand/library/graveyard/exile/command all present. |
| 500–514 Turn structure | ✅ | complete, walked from a sequence with skip effects. |
| 600–616 Spells/abilities/effects | ◐ | casting/activated/triggered/static/mana/replacement done. **Loyalty (606) not**; layers (613) partial; ordering (616.1) not. |
| 700–733 Additional | ◐ | SBAs (704) done; keyword abilities (702) recognized + flag-bound; keyword *actions* (701) partial via effects. Copying (707), DFC/Split/Saga/etc. (708–722), Monarch/Initiative/Day-Night not. |
| 800–811 Multiplayer | ✖ | stubbed — `create_multiplayer` raises, route returns 501. |
| 900–905 Casual variants | ◐ | Commander (903) damage + command zone done; **commander tax (903.8) not**. Others not. |

---

## Milestones (execute in order)

Each milestone lists its goal, the concrete work, what it unblocks, and the
reference. Frontend UI work is called out per milestone; it can proceed in
parallel once the backend seam exists.

### M1 — Oracle-effect parser (keystone)
**Goal:** arbitrary `oracle_text` → `AbilitySpec` IR → `GameEffect`, so
spells/abilities resolve without a hand-authored catalogue entry.
Follows [`09_ORACLE_EFFECT_PARSER.md`](09_ORACLE_EFFECT_PARSER.md). Phase 0
(IR + binder + one card) and the Phase 1 *keyword* catalogue are **done**.
- Normalizer + segmenter (split abilities; peel trigger/cost/keyword wrappers).
- Deterministic effect-family handler table for what the engine already
  supports (damage/draw/discard/destroy/gain_life/counter/search) with shared
  TARGET/NUMBER/DURATION sub-grammars.
- Fail-closed full-span **coverage gate** (`MODELED`/`UNMODELED`) + processing
  list for unclaimed clauses; coverage metric in tests.
- Parse-on-load in `LazyCardLoader`; bind-per-game already wired.
- **Unblocks:** the majority of instants/sorceries/abilities; is the seam M2
  and M6 plug into. *(docs/09 Phases 1–2.)*

### M2 — Parametric keyword binding
**Goal:** give behaviour to keywords already parsed-but-inert.
- Alternative/additional-cost keywords (kicker, multikicker, buyback, escape,
  flashback…) via the cost system + cast-time choices.
- Combat-math keywords (annihilator N, afflict, bushido, rampage…).
- Protection *quality*, ward, hexproof-from as targeting/replacement filters.
- **Depends on:** M1 keyword catalogue (done) + cost/targeting systems (done).
- Backlog: ToDo_Backend "Rules Engine … parser" progress note.

### M3 — Layer system completion (RULE 613)
**Goal:** finish `game/continuous.py` to the full layer set.
- Layers 1–3 (copy/control/text — copy needs RULE 707, see M6), 5 (colour),
  7a (CDAs), 7e (P/T switch).
- True dependency + timestamp ordering *within* a layer (currently
  registration order, RULE 613.7).
- **Depends on:** partial overlap with M6 copying for layer 1.

### M4 — Permanent subsystems
Independent, medium-sized; can interleave with M1–M3.
- **Loyalty / planeswalker abilities (606):** loyalty-cost kind in `costs.py`,
  sorcery-speed + once-per-turn gate, `[+N]/[-N]/[0]` activation, 0-loyalty SBA
  (704.5i), planeswalker damage marking. *UI:* clickable loyalty controls.
- **Aura / Equipment attachment (303 / 301.5 / 702.6):** Aura ETB attaches to
  target (303.4f); `equip` as a sorcery-speed activated ability; fortify/
  reconfigure; `continuous.recompute` reads `attached_to` into layers 6/7.
  *UI:* cast-target for Auras, "Ausrüsten" control, buff shown on host.
- **Commander tax (903.8):** per-commander from-command-zone cast counter on
  the player/state, read by the cost calc, carried by rewind snapshots.
- **Conditional enters-tapped (614.1):** shock/check/pain lands — a
  replacement-effect + player choice (pay life / evaluate condition) instead of
  the current boolean. *UI:* pay-2-life prompt.

### M5 — Interactive priority, multiplayer & ordering choices
**Goal:** two humans can hold priority and respond.
- Interactive priority loop (offer priority → collect action/pass → resolve on
  all-pass), replacing the current auto-pass.
- Wire `WebSocket /ws/game/{id}` into a server-held session (run action through
  engine, broadcast `GameState.to_dict()`); remove `create_multiplayer` stub.
- Interactive **blocker declaration** (opponent side).
- Player-made **ordering choices**: triggers within a controller (603.3b) and
  replacement/prevention ordering (616.1).
- **UI:** opponent zones, hidden opponent hand, turn/priority indicator,
  per-creature attacker subset selection, slow-opponent timeout.

### M6 — Card-type structures
Each is a `type_line`/layout the parser or a dedicated handler must own; most
depend on M1, and copies feed M3's layer 1.
- Double-faced & MDFC (712) + Day/Night (731); Adventure (715) & Split/Fuse (709).
- Saga (714) / Class (716) / Leveler (711) staged counters.
- Copying objects (707) — token copies, "becomes a copy of".
- Battles (310), Dungeons (309).
- Deprioritized until a deck needs one: Emblems (114), Stickers (123), Monarch
  (725) / Initiative (726), Rad counters (728), remaining multiplayer/casual
  variants.

### M7 — Product features (parallel track, not rules-engine)
- **LLM deck analysis (UC2):** `POST /api/decks/{id}/analyze` — Claude API,
  prompt templates, structured output, caching; design the `Analysis` model
  alongside (the reserved `Deck.analysis_id` shape isn't final). *UI:* analyze
  button + results view + cache indicator. Use the latest Claude models.
- **Auth & persistence:** accounts/login, scope saved decks to an owner, game
  history/session persistence. *UI:* login/signup, token storage, reconnect.
- **Bot AI (UC5):** upgrade the greedy `run_goldfish_turn` to weigh lines.
  *UI:* bot-vs-manual selector, action visualization + speed control.
- **Config module:** pull hard-coded paths/constants into `config.py` reading
  env overrides (`MTG_CACHE_DIR`, `MTG_DATA_DIR`).
- **Moxfield import proxy:** `GET /api/import/moxfield/{id}` (may still hit
  Cloudflare; needs browser-like headers or a headless fallback).

---

## Suggested sequencing

```
M1 (oracle parser) ──┬─▶ M2 (parametric keywords)
                     ├─▶ M6 (card-type structures) ──▶ M3 layer 1 (copy)
                     └─▶ (unblocks most spells)
M3 (layers) ─────────── independent of M1 except layer 1
M4 (permanent subsystems) ── independent, interleave anytime
M5 (priority/multiplayer) ── large; gates real 2-player + ordering choices
M7 (product: LLM / auth / bot) ── parallel track, no rules-engine dependency
```

**Critical path to "most decks are playable solo":** M1 → M2 + M4. Full
two-player play additionally needs M5. Everything in M6/M7 is additive.
