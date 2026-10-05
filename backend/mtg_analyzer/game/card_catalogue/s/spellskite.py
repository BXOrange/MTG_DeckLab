from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spellskite() -> list[AbilitySpec]:
    """{U/P}: Change a target of target spell or ability to this creature.
    ({U/P} can be paid with either {U} or 2 life.)

    — MEC-12 (cEDH Kinnan). `ChangeTargetEffect`'s new ``redirect_to_source``
    flag (built for this card and Hydroelectric Specimen together) — not a
    free choice among every legal alternative the way Misdirection/
    Deflecting Swat's own player-facing pick is, but forced onto Spellskite
    itself if that's even legal. No "you may" printed, so ``optional`` stays
    False: with exactly one candidate alternative (itself), that auto-applies.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("change_target", {
                "spell_or_ability": True, "redirect_to_source": True,
            })],
            cost={"mana": "{U/P}"},
        ),
    ]


register("Spellskite", _spellskite)
