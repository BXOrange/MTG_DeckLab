from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kimahri_valiant_guardian() -> list[AbilitySpec]:
    """Vigilance
    Ronso Rage — At the beginning of combat on your turn, put a +1/+1 counter on Kimahri and tap target creature an opponent controls. Then you may have Kimahri become a copy of that creature, except its name is Kimahri, Valiant Guardian and it has vigilance and this ability.

    — PLAY-ALL (Counter Blitz). Vigilance is the keyword. The trigger puts the counter, taps a creature an opponent controls, then an `optional`
    `become_copy_permanent` over that creature (``previous_subject``; ``set_name``, ``add_keywords`` vigilance, ``keep_own_abilities`` so it
    keeps Ronso Rage — **simplification:** it keeps *all* of its own abilities, not only this one).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "target_kind": None}),
                EffectSpec("tap", {"target_kind": "creature_you_dont_control"}),
                EffectSpec("optional", {"prompt": "Kimahri wird zur Kopie dieser Kreatur?", "effects": [{
                    "type": "become_copy_permanent", "params": {
                        "previous_subject": True, "set_name": "Kimahri, Valiant Guardian",
                        "add_keywords": ["vigilance"], "keep_own_abilities": True,
                    },
                }]}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Kimahri, Valiant Guardian", _kimahri_valiant_guardian)
