from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "third from the top" — the printed depth.
_LIBRARY_DEPTH = 3


def _god_eternal_bontu() -> list[AbilitySpec]:
    """Menace
    When God-Eternal Bontu enters, sacrifice any number of other permanents,
    then draw that many cards.
    When God-Eternal Bontu dies or is put into exile from the battlefield, you
    may put her into her owner's library third from the top.

    — PLAY-ALL Step 2 (World Shaper). Menace is the keyword fold-in. The ETB is
    MEC-103's `sacrifice_chosen_then` (``count: any``, ``exclude_self``,
    pick-any-number through the optional chooser: the player may stop at any point, including at zero) with a `draw` whose ``x``
    is bound to the number actually sacrificed. The leave clause is the parser's
    own `return_to_library` shape (``depth 3``) on both heads — `DIES` and
    `LEAVES_BATTLEFIELD` to exile — made optional ("you may"), as the parser
    does for "it".
    """
    library_third = EffectSpec("return_to_library", {"target_kind": None, "position": "top", "depth": _LIBRARY_DEPTH})
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_chosen_then", {
                "what": "permanent", "count": "any", "exclude_self": True, "optional": True,
                "effects": [{"type": "draw", "params": {"count": "x"}}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [library_third],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_library", {"target_kind": None, "position": "top", "depth": _LIBRARY_DEPTH})],
            trigger={
                "event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}, "to_zone": "exile",
            },
            optional=True,
        ),
    ]


register("God-Eternal Bontu", _god_eternal_bontu)
