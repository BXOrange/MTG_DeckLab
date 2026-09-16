from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mystic_sanctuary() -> list[AbilitySpec]:
    """({T}: Add {U}.)
    This land enters tapped unless you control three or more other
    Islands.
    When this land enters untapped, you may put target instant or
    sorcery card from your graveyard on top of your library.

    — Mystic Sanctuary. Its enters-tapped clause needed a new `lands.py`
    ``unless_count`` variant (a specific land *type*, "other Islands",
    rather than any other land or every basic — the "Sanctuary" cycle);
    the ETB trigger needed the new `EffectSpec.condition` key
    ``source_entered_untapped`` (RULE 614.1's own settled-before-ETB
    ordering) and `ReturnToLibraryEffect`'s existing ``graveyard_instant_
    or_sorcery`` target kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_library", {
                "target_kind": "graveyard_instant_or_sorcery", "position": "top", "optional": True,
            }, condition={"source_entered_untapped": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
    ]


register("Mystic Sanctuary", _mystic_sanctuary)
