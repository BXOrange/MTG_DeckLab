from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _worldgorger_dragon() -> list[AbilitySpec]:
    """Flying, trample
    When this creature enters, exile all other permanents you control.
    When this creature leaves the battlefield, return the exiled cards to
    the battlefield under their owners' control.

    — MEC-43 round 4D. Both keywords are plain flag keywords. The ETB
    half is `ExileEffect` with the mandatory "other permanents you control"
    mass group (ENG-61: the structured ``group``; formerly the named
    ``other_permanents_you_control`` mass selector) — unlike `ExileAnyNumber
    YouControlEffect`'s "any number" *choice*, this is unconditional, so
    it belongs with the plain board-wipe-shaped selectors instead) plus
    ``track_exiled_with=True`` (MEC-21's accumulating `GameObject.
    exiled_with_ids` tracker, newly wired into the selector branch
    alongside its pre-existing targeted-branch support). The
    leaves-battlefield half reuses `ReturnAllExiledWithEffect`
    (``"return_all_exiled_with"``) completely unchanged — built for
    Parallax Wave, and exactly the same shape here: several permanents,
    each returning to *their own* owner, which for Worldgorger Dragon is
    always its own controller since it only ever exiles its own stuff.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "group": {"zone": "battlefield", "of": "you", "filter": {"not_reference": True}}, "track_exiled_with": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_all_exiled_with", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Worldgorger Dragon", _worldgorger_dragon)
