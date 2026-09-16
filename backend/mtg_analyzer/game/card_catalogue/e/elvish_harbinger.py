from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elvish_harbinger() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for an Elf
    card, reveal it, then shuffle and put that card on top.
    {T}: Add one mana of any color.

    — Eliferate deck batch. The mana ability is bound automatically off the
    printed "{T}: Add one mana of any color." text; the ETB tutor is a
    plain `SearchLibraryEffect` — an optional, `{"type": "Elf"}`-filtered
    library search to the top of the library, the same "reveal" simplification
    (not separately modeled) every other tutor in this catalogue makes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Elf"}, "destination": "library_top", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Elvish Harbinger", _elvish_harbinger)
