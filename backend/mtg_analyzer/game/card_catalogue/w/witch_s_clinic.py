from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _witch_s_clinic() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {2}, {T}: Target commander gains lifelink until end of turn.

    — Tramplesaurus Rex deck batch. The mana ability is read off the printed text; the second is a
    `pump` granting lifelink to a creature target filtered to commanders (RULE 903.3).
    **Documented simplification:** a commander that is not a creature (lifelink would do nothing for
    it anyway) is not offered.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"keywords": ["lifelink"], "target_kind": "creature",
                                 "creature_filter": {"is_commander": True}})],
            cost={"text": "{2}, {t}"},
            raw_text="{2}, {t}: target commander gains lifelink until end of turn.",
        ),
    ]


register("Witch's Clinic", _witch_s_clinic)
