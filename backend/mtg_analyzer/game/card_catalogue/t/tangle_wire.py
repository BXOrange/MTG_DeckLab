from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 5: keyword mechanics
#
# Four RULE 702 keywords that were bare `FLAG`/parametric recognition with no
# behaviour behind them — Fading (702.32), Soulbond (702.94), Mutate
# (702.140) and Bargain — plus a *granted* Escape (702.138 from Underworld
# Breach rather than printed on the card), and the Pacts, which needed
# nothing new at all beyond the `pay_cost_then` primitive wave 2 built.
# ---------------------------------------------------------------------------


def _tangle_wire() -> list[AbilitySpec]:
    """Fading 4
    At the beginning of each player's upkeep, that player taps an untapped
    artifact, creature, or land they control for each fade counter on this
    artifact.

    — Tangle Wire. **Fading (RULE 702.32)** is now a real keyword rather
    than a recognized-but-inert one, and both halves live with the keyword
    (not with this card), so every Fading/Vanishing card gets them:

    * 702.32a's entry counters are placed by `RulesEngine.
      _apply_entry_counters`, read off the **parsed keyword** rather than
      the reminder sentence — the keyword *is* the rule, and the reminder
      text isn't guaranteed to be printed.
    * 702.32b's "At the beginning of your upkeep, remove a fade counter. If
      you can't, sacrifice it." is synthesized in
      `effect_binder._keyword_triggered_abilities`, alongside annihilator/
      afflict/bushido. Note "if you can't" means *no counter left*, not a
      choice — which is why Fading N lasts N+1 of your upkeeps, not N.

    The card's own ability then reads the counter count **live** each
    upkeep, so the tax shrinks as Fading counts down — which is the entire
    design of the card.

    **Documented simplification**: which permanents get tapped is an
    auto-pick, the same non-interactive choice the engine already makes for
    every other "that player chooses" cost.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap_permanents_per_counter", {
                "kind": "fade",
                "types": ["artifact", "creature", "land"],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
        ),
    ]


register("Tangle Wire", _tangle_wire)
