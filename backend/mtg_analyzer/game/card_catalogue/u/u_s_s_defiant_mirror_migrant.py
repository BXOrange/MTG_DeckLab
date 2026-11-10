from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _u_s_s_defiant_mirror_migrant() -> list[AbilitySpec]:
    """Flash
    When U.S.S. Defiant enters, it and up to one target creature you control phase out. (Treat them and anything attached to them as though they don't exist until your next turn.)
    Station
    8+ | Flying

    RULE 702.26: phasing out of the Spacecraft itself (``self_target``) and
    up to one chosen creature. Flash and Station fold in from the keyword
    catalogue; the 8+ flying row is the parser-claimed level static.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("phase_out", {"self_target": True}),
                EffectSpec("phase_out", {"target_kind": "creature_you_control", "optional": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["flying"], "affects": "self", "min_level": 8, "level_counter": "charge",
            })],
        ),
    ]


register("U.S.S. Defiant, Mirror Migrant", _u_s_s_defiant_mirror_migrant)
