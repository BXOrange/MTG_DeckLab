from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# a copy-spell activated ability + a graveyard-recycle land
# ===========================================================================


def _rootha_mercurial_artist() -> list[AbilitySpec]:
    """{2}, Return Rootha to its owner's hand: Copy target instant or sorcery
    spell you control. You may choose new targets for the copy."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
            cost={"mana": "{2}", "text": "{2}, Return ~ to its owner's hand"},
        ),
    ]


register("Rootha, Mercurial Artist", _rootha_mercurial_artist)
