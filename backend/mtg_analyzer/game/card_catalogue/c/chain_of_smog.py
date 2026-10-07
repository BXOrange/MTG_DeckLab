from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chain_of_smog() -> list[AbilitySpec]:
    """Target player discards two cards. That player may copy this spell
    and may choose a new target for that copy.

    — MEC-43. The targeted player decides whether to copy the resolving
    spell, then may choose the copy's target before it enters the stack.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("discard", {"count": 2, "target_kind": "player"}),
                EffectSpec("optional", {
                    "player": {"of": "target", "as": "self"},
                    "prompt": "Chain of Smog kopieren?",
                    "effects": [{"type": "copy_self_spell", "params": {
                        "controller": {"of": "target", "as": "self"},
                        "choose_new_targets": True,
                    }}],
                }),
            ],
        ),
    ]


register("Chain of Smog", _chain_of_smog)
