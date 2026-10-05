# Smart Bot

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
