from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _merciful_mandate() -> list[AbilitySpec]:
    """Untap all creatures you control. If it's a combat phase, you may end the combat phase. (Remove all attackers and blockers from combat. Exile all spells and abilities from the stack, including this spell.)

    RULE 506.1: the combat phase is the ``during_phase: combat`` gate;
    RULE 727: ending the phase is the ``end_combat_phase`` effect, wrapped
    in ``optional`` because it is a "may".
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("tap", {
                    "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
                    "untap": True,
                }),
                EffectSpec("if_else", {
                    "condition": {"kind": "during_phase", "phase": "combat"},
                    "then": [{"type": "optional", "params": {"effects": [{"type": "end_combat_phase", "params": {}}]}}],
                }),
            ],
        ),
    ]


register("Merciful Mandate", _merciful_mandate)
