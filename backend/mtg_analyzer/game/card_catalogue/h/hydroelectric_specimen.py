from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hydroelectric_specimen() -> list[AbilitySpec]:
    """When Hydroelectric Specimen enters, you may change the target of
    target instant or sorcery spell with a single target to Hydroelectric
    Specimen.

    — MEC-12 (cEDH Kinnan). The ETB-triggered, "you may" sibling of
    Spellskite's activated ability, sharing the same `redirect_to_source`
    primitive — narrowed to instant/sorcery spells by `ChangeTargetEffect`'s
    new ``card_types`` param (`targeting._spell_matches_filter`'s existing
    ``card_types`` key, previously only reachable via `CounterSpellEffect`'s
    own ``card_types``, never `ChangeTargetEffect`'s).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("change_target", {
                "card_types": ["instant", "sorcery"], "single_target": True,
                "redirect_to_source": True, "optional": True,
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
    ]


register("Hydroelectric Specimen", _hydroelectric_specimen)
register("Hydroelectric Specimen // Hydroelectric Laboratory", _hydroelectric_specimen)
