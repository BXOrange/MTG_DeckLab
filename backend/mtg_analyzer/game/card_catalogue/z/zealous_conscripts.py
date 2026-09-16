from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _zealous_conscripts() -> list[AbilitySpec]:
    """Haste. When this creature enters, gain control of target permanent
    until end of turn. Untap that permanent. It gains haste until end of
    turn.

    — Zealous Conscripts. Haste is a keyword, already covered by the
    parser's keyword catalogue. The ETB is a new atomic
    `GainControlUntilEndOfTurnEffect` this batch — control change, untap,
    and the target's own "gains haste" all bundled into one effect over one
    shared target (no existing "gain control until end of turn" primitive
    existed before this batch; confirmed via `game/effects/core.py` before
    building it — a temporary control change is a materially different,
    simpler shape than Gilded Drake's still-missing *permanent exchange*).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_control_until_eot", {"target_kind": "permanent"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Zealous Conscripts", _zealous_conscripts)
