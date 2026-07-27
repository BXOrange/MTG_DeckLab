# Completion Roadmap

The single, dependency-ordered plan for finishing the implementation. It
**sequences**; it deliberately does not restate scope. Every open item named
here is a ticket id in [`BACKLOG.md`](BACKLOG.md) — read that file for what
the work actually is.

Last re-evaluated against the code: **2026-07-27**.

## Live sources this reconciles

- Granular open items: [`BACKLOG.md`](BACKLOG.md) (backend + frontend, as
  categorized tickets)
- Examples / parser-tail strategy: [`PARSER_LONG_TAIL.md`](PARSER_LONG_TAIL.md)
- Shipped: [`Done_Backend.md`](Done_Backend.md),
  [`Done_Frontend.md`](Done_Frontend.md)
- User-facing coverage: in-app **Engine-Status** tab
  (`../../frontend/src/js/implementationStatusView.js`)
- Oracle parser design: [`09_ORACLE_EFFECT_PARSER.md`](../concepts/09_ORACLE_EFFECT_PARSER.md)
- Rule lookups: [`Reference/rules_wiki/`](../Reference/rules_wiki/) (`RULE <n>` → CR line)

---

## Where we are

The **rules engine is built and green** (2472 backend tests, 238 skipped):
the full turn/stack/priority/SBA loop, London mulligan, targeting, the whole
mana model (including RULE 605.3a spend restrictions and triggered mana
abilities), the RULE 613 layer system, the complete RULE 508/509 combat
restriction/requirement/multi-block family, the RULE 702 keyword catalogue
bound to real behaviour, RULE 616 replacement effects, commander damage +
tax, and every card-type structure except two (below) — Adventure, Split/
Fuse, Saga, DFC/MDFC, Class/Leveler, and **Battles (RULE 310)**, plus the
designation subsystems (Emblems 114, Monarch 725, Initiative 726, The Ring
701.51, Rad counters 728) and energy (122).

Three product surfaces sit on that one engine: **Goldfisch** (solo),
**Replay/Puzzle** (build an arbitrary board and play from it), and
**Multiplayer** — a real two-seat table with RULE 117 priority played out
for real, hidden-zone redaction per perspective (RULE 400.2), concede
(104.3a), take-backs, reconnect-by-name with disconnect/idle timers, and
seat-filling bots that act only through the client surface.

**The dominant remaining gap is unchanged and singular: card text does not
yet fully become behaviour.** A spell or ability does something only if its
card is hand-authored in `game/ability_catalogue.py` **or** the oracle-text
parser recognizes every one of its clauses as `MODELED` (fail-closed —
never half-resolved). That is **26.6% of the Oracle universe — 9,092 of
34,208 cards, PARSER_VERSION 34**. Re-measure with
`scripts/coverage_report.py` before trusting the figure.

Everything else open is narrow, additive, and independent of that: two card
types, a set of named mechanics with no primitive yet, engine rough edges,
scaling the table past two seats, and the product track (LLM analysis,
accounts).

---

## Comprehensive-Rules coverage at a glance

| CR area | State | Notes |
| --- | --- | --- |
| 100–123 Game concepts | ✅ | mana, life, damage, counters, targets, costs, timing, tokens, Emblems (114), energy/experience (122). Stickers (123) are a **permanent non-goal, never to be implemented** — the parser classifies any mentioning card `NEVER_SUPPORTED`, kept out of both the coverage count and the backlog ranking. |
| 200–213 Parts of a card | ✅ | Card model complete; loyalty and defense (210) both tracked and playable. |
| 300–315 Card types | ◐ | Every type modeled — incl. Aura/Equip/Fortify/Reconfigure attachment, Adventure, Split/Fuse, Saga, DFC/MDFC, Class/Leveler, Battles (310) — except **Dungeons (309)**, [TYP-2]. Face-down permanent states (morph/manifest) are the other structural gap, [TYP-1]. |
| 400–408 Zones | ✅ | all seven zones, incl. RULE 400.2 per-perspective redaction and RULE 400.7 new-object identity on zone change. |
| 500–514 Turn structure | ✅ | complete, walked from a sequence with skip effects. |
| 600–616 Spells/abilities/effects | ◐ | casting/activated/triggered/static/mana/replacement/loyalty done; layers (613) done bar three deliberately-scoped corners, [ENG-8] [ENG-9] [ENG-10]. Remaining edges: [ENG-3]–[ENG-7], [ENG-11]–[ENG-14]. |
| 700–733 Additional | ◐ | SBAs (704) done bar [ENG-1]; the RULE 702 keyword catalogue is recognized *and* bound; keyword *actions* (701) partial — the named gaps are the `MEC` tickets — and Annihilator still auto-picks its victims, [ENG-2]. Copying (707) works but isn't a true layer-1 continuous effect, [ENG-6] [ENG-10]. Monarch (725)/Initiative (726)/The Ring (701.51)/Rad counters (728) done; Initiative's "venture into the dungeon" (726.2) is blocked on [TYP-2]. |
| 800–811 Multiplayer | ◐ | A two-seat table plays for real: APNAP priority, concede (104.3a), the RULE 800.4a deferred board cleanup. Three or more seats are engine-ready but untested and unlaid-out, [PLR-2]; range-of-influence and attack-multiple-players variants are unmodeled. |
| 900–905 Casual variants | ◐ | Commander (903) — damage, command zone, tax (903.8) — done. Others deprioritized, [TYP-4]. |

---

## Milestones

Milestone ids are **stable**: M2/M3/M4/M5 stay numbered after closing so the
code comments citing them keep resolving. Frontend work is called out per
milestone and can proceed in parallel once the backend seam exists.

### Closed

- **M2 — parametric keyword binding.** Every parametric keyword this engine
  models binds onto `GameObject.parametric_keywords` *and* consumes it.
  Residue: [PAR-5] (hexproof-*from* loses its quality — overprotective,
  never rules-illegal).
- **M3 — layer system (RULE 613).** All layers implemented. Residue is three
  deliberate scopings, each safe for today's effect vocabulary and each with
  a written trigger for revisiting it: [ENG-8], [ENG-9], [ENG-10].
- **M4 — permanent subsystems.** All four shipped, engine-side and UI.
- **M5 — interactive priority & multiplayer** (shipped 2026-07-22, bots
  2026-07-27). Note the legacy `POST /api/game/multiplayer` is *still* a 501
  and that is **correct, not a gap** — it is the superseded seat-less entry
  point; the live surface is `/api/multiplayer/*` plus `/ws/lobby`. Residue,
  all narrow: [PLR-2] (3+ seats) → [PLR-8] (bots there), [PLR-3], [PLR-5],
  [PLR-6], [PLR-7], and UI polish [VIS-5] [VIS-6] [VIS-7]. The one
  engine-side piece left is subset attacker declaration, [ENG-15] → [VIS-3].

### M1 — Oracle-effect parser (keystone; a standing program, not a finite batch)

**Goal:** arbitrary `oracle_text` → `AbilitySpec` IR → `GameEffect`, so a
spell resolves without a hand-authored catalogue entry. Design:
[`09_ORACLE_EFFECT_PARSER.md`](../concepts/09_ORACLE_EFFECT_PARSER.md).

This is the critical path and the only open item with no end state. Work it
two ways, in this order of preference:

1. **Named parser gaps** — [PAR-1] through [PAR-11], each a concrete
   recognition shape blocking an identified cluster.
2. **Mechanics with no engine primitive at all** — the `MEC` tickets.
   [MEC-1] (Fight, ~40 cards) is the highest-yield next batch;
   [MEC-2] (Monstrosity/Adapt, ~63) the next.
3. **The indefinite tail** — [PAR-12], whose method, recurring lessons and
   worked samples live in [`PARSER_LONG_TAIL.md`](PARSER_LONG_TAIL.md).

Rank candidates with `processing_list.coverage_over_cards()` rather than by
intuition, and bump `PARSER_VERSION` in the same session you add a handler.

**Unblocks:** everything meant by "most decks are playable".

### M6 — Card-type structures (partial)

- **Done:** Adventure (715), Split/Fuse (709), Saga (714), DFC transform/
  MDFC, Class (716)/Leveler (711), **Battles (310)**, Emblems (114),
  Monarch (725)/Initiative (726), Rad counters (728).
- **Open:** [TYP-1] face-down permanent states (morph/manifest/megamorph) —
  a genuinely new permanent-state subsystem; [TYP-2] Dungeons (309) — zero
  scaffolding, and the blocker for RULE 726.2; [TYP-3] a general
  trigger-condition recognition gap surfaced by Prepared cards; [TYP-4]
  niche formats.
- **Permanent non-goals, not gaps:** Stickers (123) and Attractions (717).
  Neither will be implemented; stickers are enforced at the parser level as
  a `NEVER_SUPPORTED` verdict distinct from `UNMODELED`.

### M7 — Product features (parallel track, no rules-engine dependency)

- **Deck analysis (UC2):** the static/heuristic half ships client-side
  (mana curve, types, land archetypes, Command Zone categories, a
  Commander-Brackets heuristic). The LLM-backed narrative half is
  [ANA-1] → [ANA-2] [ANA-3]. Use the latest Claude models.
- **Auth & persistence:** [PLR-9] accounts (saved decks are unscoped until
  this exists) → [PLR-10] game history.
- **Bot AI (UC5):** seats are filled and playing; what's open is judgment —
  [PLR-7] a bot that weighs lines rather than taking the first legal offer —
  and [VIS-7] making a bot's turn watchable.

---

## Suggested sequencing

```code
M1 (parser gaps → mechanics → tail)  ── standing; the ONLY path to "most decks playable"
M6 remainder ([TYP-1] face-down, [TYP-2] dungeons → RULE 726.2)  ── additive, independent of M1
M5 residue ([PLR-2] 3+ seats → [PLR-8]; [ENG-15] → [VIS-3])      ── independent
M7 ([ANA-1] → [ANA-2]/[ANA-3];  [PLR-9] → [PLR-10])              ── independent
M2 / M3 / M4 ── closed; residue tracked as [PAR-5], [ENG-8], [ENG-9], [ENG-10]
```

**Critical path to "most decks are playable":** M1, alone. Two-player play
already works at two seats. Everything in M6/M7 is additive and can be taken
in any order, by anyone, at any time.
