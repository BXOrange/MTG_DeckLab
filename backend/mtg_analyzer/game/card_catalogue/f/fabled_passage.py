from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# Lands
# ---------------------------------------------------------------------------


def _fabled_passage() -> list[AbilitySpec]:
    """"{T}, Sacrifice this land: Search your library for a basic land card,
    put it onto the battlefield tapped, then shuffle. Then if you control
    four or more lands, untap that land." — a conditional-untap fetch, the
    Evolving Wilds shape plus the `untap_if_lands_at_least` search param
    (RULE 701.19; the fetched land counts itself in the total)."""
    # "four or more lands" — the trailing-conditional threshold on Fabled
    # Passage; the fetched land has already entered when the test is made.
    FABLED_PASSAGE_LAND_THRESHOLD = 4
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {"basic": True},
                        "destination": "battlefield_tapped",
                        "count": 1,
                        "optional": True,
                        "untap_if_lands_at_least": FABLED_PASSAGE_LAND_THRESHOLD,
                    },
                )
            ],
            cost={"text": "{T}, Sacrifice ~"},
        )
    ]


register("Fabled Passage", _fabled_passage)
