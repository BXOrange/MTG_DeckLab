from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _torch_the_witness() -> list[AbilitySpec]:
    """Torch the Witness deals twice X damage to target creature. If
    excess damage was dealt to that creature this way, investigate.
    (Create a Clue token. It's an artifact with "{2}, Sacrifice this
    token: Draw a card.")

    — Imodane deck batch. The new `damage_then_investigate_if_excess` —
    see its docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage_then_investigate_if_excess", {"target_kind": "creature"})],
        ),
    ]


register("Torch the Witness", _torch_the_witness)
