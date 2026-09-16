from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _keen_duelist() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you and target opponent each
    reveal the top card of your library. You each lose life equal to the
    mana value of the card revealed by the other player. You each put the
    card you revealed into your hand.

    — MEC-43 round 4F. A genuinely new simultaneous, two-player
    reveal-and-compare — no existing shape combines "each of two players
    reveals a card" with "each player's own life loss reads the *other*
    player's reveal" (the single-player `RevealTopThenTakeAndLoseLifeEffect`
    (MEC-12, Dark Confidant) only ever reads a player's own revealed
    card). Built as one atomic `MutualRevealCompareManaValueEffect`
    (`mutual_reveal_compare_mana_value`) rather than two effects sharing a
    resolve-time referent, since both reveals must happen before either
    life total changes. Fully deterministic (no player choice beyond RULE
    115's own opponent target), so no interactive `pending_choice`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mutual_reveal_compare_mana_value", {"target_kind": "opponent"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Keen Duelist", _keen_duelist)
