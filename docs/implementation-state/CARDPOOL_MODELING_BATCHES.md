# Card-pool modeling: coverage report & batch plan

Generated 2026-07-18 from a full-universe coverage run
(`backend/scripts/coverage_report.py`, ledger-backed). Re-run that script after
each batch — the number is a snapshot, not a constant.

## Coverage of the whole card pool

| Metric | Value |
| --- | --- |
| Cards in cache (full Oracle universe) | **34,209** |
| Covered (parser-`MODELED` **or** hand-`AUTHORED`) | **6,720 (19.6%)** |
| Uncovered | 27,489 |
| Distinct unclaimed templates (the backlog) | 29,392 |

"Covered" = the card actually *behaves*: the oracle parser fully modeled it, or
it's hand-registered in `game/ability_catalogue.py`. The 19.6% is the honest
denominator now that the whole ~34k universe is loaded (it replaced the old
cache-local 24–28% measured over only ~2,900 curated cards).

### The shape of the backlog (this drives the plan)

Template size = how many cards a single unclaimed clause-shape blocks:

| Template blocks… | # templates | Nature |
| --- | --- | --- |
| 100+ cards | 2 | fat head — one handler, huge payoff |
| 51–100 | 4 | |
| 21–50 | 42 | |
| 6–20 | 283 | the "meaty middle" — family handlers |
| 3–5 | 737 | rolling family waves |
| 2 | 1,362 | |
| **1** | **26,962** | **the long tail — mostly hand-authoring** |

Two facts set the strategy:

1. **The head is fat and generic.** The top ~330 templates (blocking ≥6 cards
   each) are coherent *families* — firebreathing pumps, evasion statics, Aura
   grants, upkeep triggers. One handler flips every card whose only remaining
   unclaimed clause it claims. This is the high-ROI zone.
2. **The tail is enormous and unique.** 26,962 templates block exactly one card
   — by definition not a generic shape. Reaching 100% is therefore an
   *indefinite* program of hand-authoring + narrow parser extensions, not a
   finite set of batches. The batches below take us from 19.6% to an estimated
   **~50–65%** via families; the rest is the long-term grind.

> **Caveat — the all-or-nothing gate.** A card is covered only when *every* one
> of its clauses parses. So "cards blocked" per template **overcounts** what a
> batch unlocks: a multi-clause card needs all its families done. Treat the
> per-batch card numbers below as upper bounds and **validate the real delta by
> re-running `coverage_report` after each batch** (cheap — the engineering
> ledger only re-parses changed cards).

## Batch plan

Ordered by ROI (cards per unit effort) and dependency. Each batch is one
coherent handler family + its `test_<family>.py` (parse **and** execute, per
`tests/test_counter_family.py`), following the project's existing wave cadence.
"Recognition-only" = reuses an `EffectSpec` type the binder already knows (just
add a `HANDLERS`/static/keyword row); "new primitive" = also needs a
`GameEffect` + binder case, or a new engine subsystem.

Card-blocks below are from the current ranked backlog (upper bounds).

| # | Family | ~card-blocks | Kind | Interleaved edge cases (ToDo_EdgeCases) |
| --- | --- | --- | --- | --- |
| **1 ✅** | **Firebreathing / "until end of turn" activated pumps** — `<cost>: this creature gets ±N/±N`, `gains <keyword> until EOT`, `activate only once each turn` / `only as a sorcery` | ~860 | recognition-mostly (pump + activated-cost parser exist) | layer-6 grant of an *activated* ability (#35, Umbral Mantle) |
| **2 ✅** | **Combat / evasion static clauses** — `can't block`, `can't be blocked [by …]`, `attacks each combat if able`, `can block only …`, `can't attack unless …` | ~1,326 | recognition-mostly (`combat.py` knows evasion; needs static-clause parsing) | hexproof-from-`<quality>` collapse (#1) |
| **3 ✅** | **Aura / Equipment attached-permanent grants** — `enchanted/equipped creature has <kw>`, `… gets +N/+N and has <kw>`, `doesn't untap`, `can't attack or block`, `you control enchanted creature`, aura ETB (`draw a card`, `tap enchanted creature`) + `return this aura to hand` | ~934 | recognition-mostly (`affects="attached_permanent"` exists) | re-validate existing attachment legality each SBA pass (#2); "defending player" off reconfigure stamp (#12) |
| **4 ✅** | **Self-referential triggers** — `at the beginning of your/each upkeep, …` (spore counters, `sacrifice unless you pay`), `whenever this creature attacks, +N/+N`, landfall pumps, `deals combat damage to a player, put a counter`, `draw a card at next upkeep` | ~1,812 | mixed (some new trigger conditions) | per-firing "that creature/token" dynamic ref (#13) |
| **5 ✅** | **Modal-block cleanup** — `choose N —`, `choose N or both/more —`, ETB `choose N —` | ~516 | falls out of 1–4 (bullets hold those effects); this batch closes the residual modal blocks | inline two-way modal, no header (#59, Pemmin's Aura) |
| **6** | **Cost-keyword mechanics** — landcycling / basic landcycling, megamorph, escape, multikicker, strive, kicker-counter variants | ~281 | some new keyword mechanics | kicked-spell "if kicked … instead" override; `{E}` energy pips (#24) |
| **7** | **Choose-a-type-as-enters + scoped lords** — `as this <perm> enters, choose a creature type`, `all <subtype> have <kw>`, `<scope> creatures you own have <kw>`, `all creatures get -N/-N` | ~171 | recognition (extends the shipped anthem/lord parser) | color-scoped & landwalk-grant lord edges (memory: static-lord-anthem-gap) |
| **8** | **Permission / "you may" statics** — extra land per turn, no maximum hand size, `may choose not to untap`, Leyline `begin the game … on the battlefield` | ~134 | recognition + a couple new statics | — |
| **9** | **Saga / conditional transform** — `III — exile this Saga, return transformed`, `if no spells were cast, transform`, `<cost>: transform, only as a sorcery` | ~47 | new conditional-transform family | bespoke conditional transform triggers (#16, Delver); Class static+"becomes level N" (#18) |
| **10** | **Monarch / Initiative / Emblem subsystems** — `become the monarch`, `take the initiative`, `you get an emblem with …` | ~158 | **new engine subsystems** (deferred in roadmap M1/M6) | — |
| **11+** | **Rolling 3–5-card clusters** — the ~2,100 templates blocking 2–5 cards each, grouped into families as they surface in the ranked list | ~5,000 (cumulative) | mixed generic handlers | swept per-subsystem as batches touch them |

### Progress log (real re-measures)

| After | Coverage | Δ cards | Notes |
| --- | --- | --- | --- |
| baseline | 6,720 / 34,209 (19.6%) | — | full-universe import |
| **Batch 1** | **7,358 / 34,209 (21.5%)** | **+638** | self-reference fold (`this creature`→`~`, `normalize._fold_self_reference`) + firebreathing/until-EOT activated pumps + `Activate only as a sorcery` marker (`ActivationCost.sorcery_speed_only`). `PARSER_VERSION` → `"3"`. Tests: `backend/tests/test_firebreathing_family.py`. Bonus: the fold *merged* the "this creature"/named-self templates, so combat-static phrasings now share one template — Batch 2 claims both at once. **Deferred:** monstrosity/adapt (need new `is_monstrous` flag + a "becomes monstrous" trigger event + effect types — a clean separate mechanic, ~63 cards). |
| **Batch 2** | **7,500 / 34,209 (21.9%)** | **+142** | combat-restriction static family: `~`/attached-permanent "can't attack"/"can't block"/"can't be blocked"/"can't block and can't be blocked"/"can't attack or block[, and its activated abilities can't be activated]"/"attacks each combat if able" — synthetic layer-6 flags (`cant_attack`/`cant_block`/`cant_be_blocked`/`attacks_if_able`) reusing the existing `grant_keyword`/`activation_prohibition` `StaticAbility` machinery, plus three small engine predicate checks (`GameEngine._can_attack`/`can_block`/new `_enforce_attacks_if_able`, hooked into `advance_step` since `declare_attackers` is additive and has no "done" signal of its own). Also fixed a Batch-1 regression (`_NO_UNTAP_RE` still matched the old `"this <type>"` wording the self-reference fold had already replaced with `~`) and generalized `no_untap` to `affects="attached_permanent"` (Paralyzing Grasp-shaped). `PARSER_VERSION` → `"4"`. Tests: `backend/tests/test_combat_restriction_family.py`. **Deliberately deferred** (fail-closed, stay unclaimed): every qualified/conditional variant — "can't be blocked by/except &lt;filter&gt;", "can't attack unless …", "…alone", "…unless they're mana abilities" — and the large separate family of *targeted, resolve-time* "target creature can't block this turn" activated/triggered effects (a different shape entirely, own future batch). The ~1,326 upper bound way overcounts the real gain because of the all-or-nothing coverage gate — most blocked cards have other unclaimed clauses too. |
| **Batch 3** | **7,516 / 34,209 (22.0%)** | **+16** | "you control enchanted creature/permanent" (`control_change`, already `affects="attached_permanent"` by default — zero new engine code) + Aura/Equipment quoted-ability grants (`<subject> has "<ability>"`, `<subject> gets +N/+N and has "<ability>"`) recursively parsed via `segmenter.segment_line` and wrapped as `grant_triggered_ability`, but **only** for a plain self-scoped trigger on ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS (the only events `_granted_trigger_condition` scopes correctly today). `PARSER_VERSION` → `"5"`. Small net gain despite ~130-card raw template hits because most real "has '…'" cards grant an *activated* ability instead (`{T}: …`) or a controller-scoped phase trigger ("at the beginning of your upkeep") — both deliberately deferred below — and the all-or-nothing gate means a flipped clause often isn't a card's only unclaimed one. Tests: `backend/tests/test_aura_equipment_grant_family.py`. **Deferred:** quoted **activated**-ability grants (needs a real "grant an activated ability" layer-6 primitive — ToDo_EdgeCases #35/Umbral Mantle); quoted **DAMAGE**-event grants ("deals combat damage to a player" isn't in the oracle parser's trigger-event vocabulary at all yet, a pre-existing gap unrelated to grants); quoted **phase/upkeep** grants (controller-scoped "your upkeep"/"your end step" is a pre-existing gap for even a top-level card's own ability — `segmenter.py`'s `_PHASE_TRIGGER_RE` docstring already flagged this); aura ETB effects ("when ~ enters, tap enchanted permanent"); "return this aura to hand" triggers; the qualified combat-restriction variants left over from Batch 2. |
| **Batch 4** | **7,672 / 34,209 (22.4%)** | **+156** | Two foundational primitives + one cheap recognition fix: (1) **RULE 207.2c ability-word stripping** (`normalize._strip_ability_words` — Landfall/Constellation/Battalion labels carry no rules meaning, so stripping the leading "`<Word>` — " lets the ordinary trigger grammar behind it recognize the body — Landfall pumps now fall out of the *existing* `_GROUP_SUBJECT_RE`/pump handler with zero new code); (2) **controller-scoped phase triggers** (RULE 500.7 — "at the beginning of your/each opponent's `<step>`", `AbilitySpec.trigger["phase_relation"]` + a new `effect_binder._trigger_condition` predicate checking `context.state.active_player` against the source's controller — a pre-existing gap flagged twice in Batch 2/3, closed for both `"you"` and `"not_you"`); (3) **self-subject "deals (combat) damage to a player/creature"** (RULE 120.3, `segmenter._SELF_DAMAGE_TRIGGER_RE` — `EventType.DAMAGE` + `{"combat", "is_player"}` filter). Bonus: extended `grant_triggered_ability`/`continuous._granted_trigger_condition` to DAMAGE events too (event-subject-key-aware, mirroring `effect_binder._subject_event_key`), closing Batch 3's deferred quoted-DAMAGE-grant gap (Combat Research now models). `PARSER_VERSION` → `"6"`. Tests: `backend/tests/test_phase_and_damage_triggers.py` (18, parse+execute). **Deferred:** "sacrifice `<name>` unless you pay `<cost>`" body (a real new effect primitive — needs an interactive pay-or-lose-it choice, not just recognition — the single biggest remaining upkeep-trigger template at 45 cards, now blocked *only* by this, not phase-scoping); "draw a card at the beginning of the next turn's upkeep" (a delayed-trigger phrasing distinct from a standing phase trigger); conditional-transform upkeep triggers (Delver-shaped, ToDo_EdgeCases #16); group-subject damage triggers ("a creature you control deals combat damage to a player"). |
| **Batch 5** | **7,774 / 34,209 (22.7%)** | **+102** | Investigation first: the ranked "choose `<n>` —" backlog (306 cards) turned out **not** to be a header-recognition gap at all — `catalogue/modal.py` already splits/parses every real modal block correctly; the all-or-nothing gate (`gate.py`'s `_process_modal_block`) marks *every* mode body unclaimed (even ones that parse fine standalone) whenever any one sibling mode fails, so the header shows up in the ranking as a proxy for "some mode still has a real gap", not a fixable template of its own. Sampling the genuinely-failing mode bodies (re-running `_parse_mode_body` per bullet, not just reading the aggregated `unclaimed` list) surfaced three real, cross-cutting gaps — none specific to modal blocks, so each also unlocks ordinary non-modal cards: (1) **bare "proliferate."** (RULE 701.30) — `ProliferateEffect` already existed, it just had no oracle-text handler at all (one-line `EffectHandler` addition); (2) **targeted "target player gains/loses N life"** — `GainLifeEffect` gained an opt-in `target_kind` mirroring `LoseLifeEffect`'s existing one, and along the way caught a real latent bug: `_lose_life`'s regex already *matched* "target player loses N life" but silently discarded which alternative matched, so it was binding as an untargeted "you lose N life" — now fixed to actually thread `target_kind="player"` through; (3) **"target creature with power/toughness/keyword quality"** (`targeting.TargetSpec.creature_filter`, new — `DestroyEffect`/`ExileEffect` `creature_filter=`) for "destroy/exile target creature with power N or greater/less, toughness N or greater, or a closed keyword list (flying/defender/…)". `PARSER_VERSION` → `"7"`. Tests: `backend/tests/test_modal_creature_filter_family.py` (17, parse+execute, incl. a `targeting.legal_targets` check that the filter actually narrows the offered targets). **Deferred** (fail-closed): "proliferate twice"/"…x times" (needs a repeat-count param `ProliferateEffect` doesn't have); a compound creature filter ("power 4 or greater and flying"); "exile target player's graveyard" (needs a new "whole graveyard" effect, not just recognition); "target creature you control fights target creature …" (RULE 701.?? fight — no `FightEffect` exists at all yet, a genuinely new primitive, ~40 cards across templates — good Batch 6/7 candidate); "manifest dread"/"open an attraction"/monarch-adjacent modes (new subsystems, already tracked as Batch 10). |

**Estimated trajectory** (validate each with a real re-measure):

- After Batches 1–4 (the fat head): ~**30–35%** covered.
- After Batches 5–10: ~**40–50%**.
- After Batches 11+ (2–5-card clusters): ~**55–65%**.

## The long tail → 100% (indefinite program)

The remaining ~26,962 single-card templates are, by construction, not generic.
Closing them is the "all ~30k cards, long term" ambition and proceeds two ways,
per the approved plan:

1. **Narrow parser extensions** for any singleton shapes that still generalize a
   little (a slightly-different targeting scope, a compound filter) — preferred,
   since each still pays off across a small cluster.
2. **Hand-authoring** genuinely unique cards in `game/ability_catalogue.py`
   (guide: `docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md`), only after
   confirming no near-miss handler would unlock a cluster of them.

This is a sustained grind, not a finite batch list; the cache also grows with
each new set. `coverage_report` is re-run periodically and the loop continues
against whatever the head of the backlog is by then. A handful of items are
deliberate non-goals (legacy pre-2021 werewolf template; silver-border /
acorn / un-set cards) and are excluded from the denominator or accepted as
permanently unmodeled.

## Execution mechanics (unchanged from the plan)

- **Deterministic-first**: classification, scaffolding, and measurement are pure
  code (no LLM). LLM/subagent effort (Sonnet/Haiku only, file-ownership waves)
  is spent only on finalizing a handler's regex/builder semantics and
  hand-authoring the tail.
- **Ledger** (`services/coverage_db.py`): mark each template handled; a
  re-measure only re-parses changed cards.
- **Keep docs honest**: after each batch, update the coverage figure in
  `CLAUDE.md` / the Engine-Status tab and move finished items ToDo→Done.
