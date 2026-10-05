from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _accursed_duneyard() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {2}, {T}: Regenerate target Shade, Skeleton, Specter, Spirit, Vampire, Wraith, or Zombie.

    — PLAY-ALL Step 2 (Eternal Might). The mana ability is parsed from the printed text. The regeneration is the
    shipped `regenerate` effect with a ``subtype_any`` creature filter (the OR-within-itself filter key) over the
    seven listed creature types.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("regenerate", {
                "target_kind": "creature",
                "creature_filter": {"subtype_any": ["shade", "skeleton", "specter", "spirit", "vampire", "wraith", "zombie"]},
            })],
            cost={"mana": "{2}", "taps_self": True},
        ),
    ]


register("Accursed Duneyard", _accursed_duneyard)
