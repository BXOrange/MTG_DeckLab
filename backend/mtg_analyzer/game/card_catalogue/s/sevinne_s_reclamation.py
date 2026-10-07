from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sevinnes_reclamation() -> list[AbilitySpec]:
    """Return target permanent card with mana value 3 or less from your
    graveyard to the battlefield. If this spell was cast from a
    graveyard, you may copy this spell and may choose a new target for
    the copy.
    Flashback {4}{W} (You may cast this card from your graveyard for its
    flashback cost. Then exile it.)

    — MEC-42. The graveyard-cast rider offers an optional copy after
    reanimation; its targets are chosen before the copy enters the stack.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_permanent", "max_mana_value": 3,
                    "destination": "battlefield",
                }),
                EffectSpec("if_else", {"condition": {"kind": "source_cast_via_flashback"},
                            "then": [{"type": "optional", "params": {
                                "prompt": "Sevinne’s Reclamation kopieren?",
                                "effects": [{"type": "copy_self_spell", "params": {
                                    "choose_new_targets": True,
                                }}],
                            }}], "else": []}),
            ],
        ),
    ]


register("Sevinne's Reclamation", _sevinnes_reclamation)
