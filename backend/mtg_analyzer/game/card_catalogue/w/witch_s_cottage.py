from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _witch_s_cottage() -> list[AbilitySpec]:
    """({T}: Add {B}.)
    This land enters tapped unless you control three or more other Swamps.
    When this land enters untapped, you may put target creature card from your graveyard on top of your library.

    — PLAY-ALL Step 2 (Wretched Ranks). Mystic Sanctuary's shape for creature cards: the enters-tapped clause and the
    mana ability are parsed from the text; the trigger is `return_to_library` (top, optional) with a RULE 603.4
    intervening-if (`trigger["active_if"]`, ``source_untapped``) so a tapped Cottage never asks for a target.
    """
    return [AbilitySpec(
        "triggered",
        [EffectSpec("return_to_library", {
            "target_kind": "graveyard_creature", "position": "top", "optional": True,
        })],
        trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"},
                 "active_if": {"kind": "source_untapped"}},
    )]


register("Witch's Cottage", _witch_s_cottage)
