from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec
from ...card_registry.core import register


def _qasali_ambusher() -> list[AbilitySpec]:
    """Reach
    If a creature is attacking you and you control a Forest and a Plains, you may cast this creature without paying
    its mana cost and as though it had flash.

    PAR-226. The free cast and its bundled flash are one permission (RULE 118.9 / 702.8), so they share one
    `free_cast_condition` gate: the named `creature_attacking_you_and_control_land_types` (Submerge-style: a creature
    attacking *you*, not a planeswalker you protect, RULE 506.2; a Forest and a Plains you control, RULE 205.3i), with
    ``grants_flash`` letting `GameEngine.can_cast` skip the sorcery-timing check for that free cast only. Paying the
    real {3}{G} at sorcery speed stays an ordinary cast.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "reach"}),
        AbilitySpec(
            "spell_effect",
            [],
            free_cast_condition={
                "creature_attacking_you_and_control_land_types": {
                    "land_types": ["forest", "plains"], "grants_flash": True,
                },
            },
        ),
    ]


register("Qasali Ambusher", _qasali_ambusher)
