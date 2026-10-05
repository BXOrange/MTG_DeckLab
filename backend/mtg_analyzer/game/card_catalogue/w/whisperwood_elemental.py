from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _whisperwood_elemental() -> list[AbilitySpec]:
    """At the beginning of your end step, manifest the top card of your library. (Put it onto the battlefield face down as a 2/2 creature. Turn it face up any time for its mana cost if it's a creature card.)
    Sacrifice this creature: Until end of turn, face-up nontoken creatures you control gain "When this creature dies, manifest the top card of your library."

    — PLAY-ALL (Jump Scare!). The end-step manifest is the parser's. The sacrifice ability is `grant_until` over a
    `grant_triggered_ability` static: ``lock_group`` fixes the face-up nontoken creatures you control as the ability
    resolves (RULE 611.2c) and each gets a DIES trigger that manifests the top card of its controller's library.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("manifest", {"count": 1, "kind": "manifest"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None, "lock_group": True,
                "static": {"type": "grant_triggered_ability", "params": {
                    "affects": "creatures_you_control", "object_filter": {"nontoken": True, "face_up": True},
                    "trigger_event": EventType.DIES,
                    "grant_effects": [{"type": "manifest", "params": {"count": 1, "kind": "manifest"}}],
                }},
            })],
            cost={"text": "Sacrifice ~"},
        ),
    ]


register("Whisperwood Elemental", _whisperwood_elemental)
