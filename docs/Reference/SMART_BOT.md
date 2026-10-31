# Smart Bot

Deck-by-deck review of the locally saved lists, including SmartBot 1 versus 2:
[SmartBot deck audit (22 October 2026)](SMART_BOT_DECK_AUDIT.md).

Proposed SmartBot 2 redesign, delivery stages and acceptance scenarios:
[SmartBot 2 improvement plan](../concepts/SMART_BOT_2_IMPROVEMENT_PLAN.md).

`SmartBot` (`kind="smart"`, label **Smart Bot**) is an additional opponent in
Solo and Multiplayer. Existing diagnostic bots keep their policies. Both
pickers consume the server catalogue, so registering the policy makes it
available in both without separate frontend lists.

## Knowledge and planning

The session captures own-deck definitions from setup inputs. `bot_strategy.py`
reduces them to names/quantities, costs, identities and Oracle-text roles;
no draw order reaches the policy. Runtime decisions use only
`session.view(perspective=bot.player_id)` and parameterized legal actions.
Opposing hands and all libraries remain hidden; library counts remain public.

Identity is the union of included card identities. Archetype is a heuristic:
matched combos, commander-weighted token/graveyard/sacrifice/lifegain/Voltron/
spellslinger themes, then control/aggro/ramp/midrange. Colours inform mana
choices; they do not substitute for the actual cards' roles. Commander themes
receive more weight than an isolated support card.

An initialized local Spellbook snapshot supplies fixed-name/quantity matches.
Unresolved template requirements are excluded. Missing data causes no network
call and leaves theme/role planning plus the built-in Oracle/Consultation
recipe available. Profiles are cached for the session, including restart;
new games detect from their newly supplied deck lists.

Each action re-evaluates visible progress. Closest combos receive stronger
votes, affordable pieces and tutors outrank unrelated curve filler, and tutors
prefer missing ingredients over duplicates already on the battlefield.
Development favours mana early and draw with a depleted hand. Land choices
prefer colours needed by hand/command costs and known untapped entries.
The engine continues to decide legality and pay costs through auto-tapping.

Mulligans stop after two attempts and London bottoming preserves two lands and
valuable plan pieces. Counterspells wait for opposing stack items; beneficial
and harmful targets prefer the appropriate controller. Symmetric removal waits
for a favourable creature-board comparison. Combat preserves combo pieces and
avoids obvious losing attacks; blocks favour survival/trades or preventing
lethal damage. Repeatable activations require visible resource/board progress
and have a 64-use per-ability/turn ceiling, retained across lobby bot rebuilds
and cleared on restart.

## Mana the engine does not offer

The engine offers `cast_spell` only when plain untapped sources can pay;
auto-tap never spends sacrifice or hand-exile sources (Lotus Petal, Treasures,
Elvish Spirit Guide) although the view's mana potential counts them. For a
combo piece or the commander (a permanent) that is payable *with* them but
not offered, Smart Bot first puts the scarcest missing colour into the pool
with a manual `tap_for_mana` / `activate_hand_mana`, then casts it on the next
call — at most once per card and turn, so an unexpected refusal cannot burn
sources. Commander tax comes from the public `commander_casts` count on the
player view (RULE 903.8). Other spells never trigger this.

Entry choices follow the same need-based logic: a shock land is paid for when
the hand or command zone holds something to cast and life is above a floor
(`SHOCK_LIFE_FLOOR`), a "reveal a card" land always reveals, Mox Diamond is
only cast with a spare land (and discards the land needed least). The
mulligan counts lands plus cheap mana rocks/rituals, and lands are never
tutors (a fetch land no longer earns the tutor bonus). A land's own mana
ability is not activated for its own sake; spells auto-tap it.

## Concrete winning sequence and limits

Thassa's Oracle + Demonic Consultation is recognized from the included cards
without Spellbook. Oracle waits for Consultation in hand and a coherent mana
variation paying UU+B (independent colour maxima cannot prove that). After
Oracle resolves, Consultation is cast with Oracle's own entry trigger pending.
Card naming chooses a known deck name whose copies are visibly outside the
library; the existing browser free-text naming action is explicitly exposed
in `legal_actions` for the same parameterized bot use. The engine exiles the
library and resolves Oracle's win trigger. A full-engine regression proves
this sequence, alongside commander development and combat victory.

This is a bounded heuristic policy, not a search engine or universal combo
solver. Generic Spellbook matches guide assembly; their prose is not executable
code. Complex activation costs, timing restrictions, attack taxes, special
blocking keywords and conditional alternate wins can still outstrip the
heuristics. Engine coverage still determines what cards can actually do.

## Smart Bot 2 — independent mechanic and style policy

`smart2` now replaces the inherited play, target, choice, combat and timing
policies. `smart` and the diagnostic bots retain their policies; the default
remains `smart`. SmartBot 2 reuses dispatch/entry/mana-unlocking wire helpers,
not SmartBot 1's hard prohibition on combo-piece attacks or fair sacrifices.

The implementation is in `services/smart_bot2/` and
`bot_policies/smart2.py`. Its separate, versioned profile combines the existing
archetype catalogue, mechanic roles, typal evidence and continuous style
features (initiative, reactivity, engine dependence, board width, graveyard,
spells, lands, counters and damage channels). Stored archetypes are hints;
card/commander names never award action points. Spellbook names identify
ingredients only. Missing/uninitialized snapshots remain offline-safe; Smart2
opens initialized snapshots read-only. Both printed faces are known setup
information and offered back/fused faces are evaluated with their own effects
and characteristics.

The current visible position determines whether to develop, pressure or
stabilize. Casts/activations compare net resource/effect utility, spent cards,
actual offered mana costs, chosen targets/costs, plan progress and passing.
Separate saturated synergy terms replace per-role bonus stacking. Instants
are not cast simply because they are instants: permission compares the public
threat against keeping the card, and useful responses/continuations can reserve
mana. Empty-stack end-step actions are allowed; turn-yield is withheld while
own visible instant/activated-ability windows might matter.

Choices distinguish sacrifice output from retention value, graveyard value
from discard cost, cheap transformation input from a valuable copy target,
crew power from an exact count, and equipment redistribution from a no-op.
X candidates include minimum, one, reserve-preserving values, visible target
thresholds and maximum. Optional known draw/token/reanimation/copy payments
use offered costs, including energy; unknown optional effects retain a
conservative fallback. Scry/surveil away and ordering phases are respected.

Combat estimates public trades, first/double strike, deathtouch, trample,
attack/hit value, alternative toughness assignment, ordinary/poison/commander
lethal, defender choice and defensive reserves. Combo membership does not
forbid attacking. Large equivalent armies have an aggregate path; mixed
boards use bounded candidate packages. These are estimates, not an exhaustive
adversarial combat search. Legal offered defenders/blockers remain authoritative.

The two-action projections cover enabler→payoff, landfall-before-land,
resource/untap returns, second-spell windows, effect thresholds and visible
alternative-win setup. Executable library depletion uses effect semantics:
Oracle-shaped triggered wins can use absent-name depletion or duplicate-name
exile, with coherent joint mana and duplicate-copy checks. Real-engine tests
execute both Oracle/Consultation and Oracle/Pact and a resource/untap motor.
Unknown Spellbook prose remains an assembly signal. Detected, reachable,
startable and in-execution plans are diagnostic states; only engine outcomes
count as actual wins. This remains a bounded heuristic, not a universal combo
or conditional-win solver.

### Bounds, lifecycle and diagnostics

- `MAX_CANDIDATES=128`, `MAX_COMBAT_PACKAGES=32`, top eight trace candidates,
  and 64 uses per ability/turn bound work. X thresholds and target-sampling
  avoid enumerating arbitrary integers. Plans re-evaluate after each action.
- Profiles and runtime memory use separate Smart2 session keys. Rebuilding a
  bot preserves reservations/repeat guards. Restart/rewind/takeback clear
  timeline-specific memory; cached deck priors remain independent of gameplay.
- `GameSession.view(perspective=seat)` exposes that seat's latest
  `bot_decision`: role, style vector, reservation, chosen action, utility terms
  and inferred plan status. Other seats and spectators receive no such trace.
- The wire supplies public `turn_facts` (spell/land counts and life changes),
  card `oracle_text`, and offered effective costs. Face-down exile scrubs the
  added text with the other identity fields. No opponent hand or hidden
  library contents/order is used, even by diagnostic-view evaluation.
- Proliferate uses a real recipient selection (RULE 701.34a). Smart1 and
  Smart2 sum all counter kinds on each recipient and select only positive
  totals; Smart2 also uses the selectable gain when deciding whether to pay
  for proliferation. Own loyalty/+1/+1/shield/energy/experience is beneficial;
  opposing -1/-1/stun/poison/rad/age is beneficial. Named resources require
  Oracle evidence; time counters distinguish vanishing from countdown rewards,
  Saga lore avoids speculative final-chapter sacrifice, and Battle defense
  follows its protector. Unknown/redundant keyword counters are neutral.
  Mixed counters are inseparable; near-lethal poison and an explicitly
  reachable state-triggered counter win dominate ordinary resource progress. These are conservative heuristics, not a full Oracle-text evaluator.
- The player receives the same public-state recommendation as editable
  checkboxes, with every existing counter kind and its before/after amount.
  Nothing changes until confirmation. An empty selection is legal; repeated
  proliferation gets a fresh selection. Atomic confirmation rejects duplicate,
  unknown and stale IDs; pending picks and follow-up receipts survive undo.
  Unrecognized mechanics and complex conditional wins retain heuristic limits.

### Reproducible evaluation

`backend/scripts/benchmark_smart_bot2.py` measures paired policies with fixed
shuffle/mulligan/rules seeds, seats and opponent program. It writes a source-
and deck-fingerprinted manifest, per-match results, censored budget/stall/error
outcomes, all candidate action rejections and decision-time percentiles.
Generated development/validation/test groups are independent of local deck
names; the held-out support shell composes additional abilities. Unknown
engine text is reported separately from policy quality. The script supports
an explicitly supplied trusted historical policy source via
`--baseline-source`; baseline source is never dynamically loaded from cards.

For example, with isolated `MTG_DATA_DIR` and `MTG_CACHE_DIR`:

```bash
backend/venv/bin/python backend/scripts/benchmark_smart_bot2.py \
  --output /tmp/smart2-comparison --split test --seeds 2 --workers 3
```

For known saved-deck regressions, additionally pass explicit `--decks-db` and
`--cards-db` paths (read-only); cubes and unresolved identities are recorded
as exclusions. The saved lists are already-known regressions, not untouched
holdouts. [Validation evidence](SMART_BOT_2_VALIDATION.md) records the measured
scope and its limits. The [design](../concepts/SMART_BOT_2_IMPROVEMENT_PLAN.md)
describes the generalization contract.

## Upstream research informing the design

These sources describe distinct approaches; the policy is implemented locally
and does not copy their code or depend on those engines.

- [Forge AI documentation](https://github.com/Card-Forge/forge/blob/master/docs/AI.md):
  effect-specific heuristics, strong aggro/midrange performance and explicitly
  weaker combo handling. This motivates preserving predictable diagnostic bots
  while adding deck-plan votes rather than only cheapest-first casting.
- [Forge SpellAbilityPicker](https://github.com/Card-Forge/forge/blob/master/forge-ai/src/main/java/forge/ai/simulation/SpellAbilityPicker.java):
  evaluates candidate actions against a state score, builds plans, revalidates
  them after state changes and considers waiting for a later phase. Smart Bot
  adopts re-evaluation and pass/timing decisions; it does not implement Forge's
  engine-copy simulations.
- [Bowling et al., *Toward a Competitive Agent Framework for Magic: The Gathering*](https://journals.flvc.org/FLAIRS/article/download/128416/130109/218220)
  (FLAIRS 2021): strategy-based card prioritization and synergy-oriented agent
  evaluation. It motivates commander/deck themes and progress votes; the
  project makes no claim of equivalent win rates or identical scoring.
- [mage-bench architecture](https://github.com/GregorStocks/mage-bench/blob/master/doc/architecture.md):
  external LLM pilots drive standard XMage clients through legal-action tools;
  bridges handle auto-tapping and bounded flow. The transferable boundary is
  normal-client access and guarded action loops. Smart Bot runs locally with
  deterministic heuristics and requires no LLM service.
