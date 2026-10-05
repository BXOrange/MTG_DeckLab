from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elven_passage() -> list[AbilitySpec]:
    """{T}, Pay 1 life, Sacrifice this land: Search your library for a basic
    land card, put it onto the battlefield tapped, then shuffle. You may
    behold an Elf. If you do, untap that land.

    — PAR-30 (Collect Evidence / Forage / Blight residue). A fetch land
    whose second sentence is a reflexive "behold an Elf → untap the fetched
    land". The `search` effect's ``remember=True`` stamps the found land's
    id onto this ability's own (now-sacrificed) source
    (`GameObject.linked_exile_id`, the O-Ring field); `may_behold_untap_
    linked` reads it back, beholds if able, and untaps it. See that
    effect's docstring for the "you may" auto-take simplification.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("search", {
                    "criteria": {"basic": True},
                    "destination": "battlefield_tapped",
                    "optional": True, "remember": True,
                }),
                EffectSpec("may_behold_untap_linked", {"quality": "Elf"}),
            ],
            cost={"text": "{T}, Pay 1 life, Sacrifice ~",
                  "taps_self": True, "pay_life": 1, "sacrifice": "self"},
        ),
    ]


register("Elven Passage", _elven_passage)
