from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 3: control & zone effects
#
# Five shapes the engine had no way to express, each now a whitelisted
# primitive: a two-way control **exchange** (RULE 701.10, distinct from both
# shipped control shapes), **mass phasing** plus a player-scoped life lock
# (RULE 702.26b/119.6), pulling a **spell** off the stack into hand (RULE
# 400.1, distinct from bouncing a permanent), a bounce whose legal set
# depends on the *entering* permanent, and putting cards onto the
# battlefield from **hand**.
# ---------------------------------------------------------------------------


def _gilded_drake() -> list[AbilitySpec]:
    """Flying
    When this creature enters, exchange control of this creature and up to
    one target creature an opponent controls. If you don't or can't make an
    exchange, sacrifice this creature. This ability still resolves if its
    target becomes illegal.

    — Gilded Drake. Needed a genuine **control-exchange** primitive (RULE
    701.10): the shipped layer-2 ``control_change`` static reassigns one
    permanent for as long as its source sticks around, and
    `GainControlUntilEndOfTurnEffect` is a one-way, end-of-turn grab.
    Exchange is two-way, permanent, and survives its source leaving — the
    drake dying afterwards must *not* hand the creature back, which is
    exactly why the card sees play. So it's modeled as a straight
    `controller_id` swap (RULE 701.10c's one-shot change of control), not as
    a pair of continuous effects.

    "If you don't or can't make an exchange, sacrifice this creature" is
    RULE 701.10d — an exchange with only one exchangeable permanent doesn't
    happen at all — and falls out naturally: ``optional=True`` on the target
    makes "no target" a legal choice, so the ability resolves, the exchange
    doesn't, and the sacrifice does (RULE 701.16c: sacrifice, never
    destruction, so nothing can regenerate out of it).

    Flying comes from the RULE 702 keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control", {
                "target_kind": "creature",
                "sacrifice_self_if_no_exchange": True,
                "optional": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
        ),
    ]


register("Gilded Drake", _gilded_drake)
