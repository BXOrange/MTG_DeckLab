from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _saheeli_radiant_creator() -> list[AbilitySpec]:
    """Whenever you cast an Artificer or artifact spell, you get {E} (an energy counter).
    At the beginning of combat on your turn, you may pay {E}{E}{E}. When you do, create a token that's a copy of target permanent you control, except it's a 5/5 artifact creature in addition to its other types and has haste. Sacrifice it at the beginning of the next end step.

    — PLAY-ALL (Living Energy). The cast trigger is the parser's spell filter. The combat trigger is Sample Collector's
    `pay_cost_then` with a reflexive ``then_trigger`` (so the copy's target is chosen once the energy is paid) over
    `copy_permanent` (``set_power``/``set_toughness`` 5, ``add_types``, ``haste``) and Kiki-Jiki's end-step sacrifice.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 1, "kind": "energy"})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"any_of": [{"subtype": "artificer"}, {"card_type": "artifact"}]},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {"cost": "pay {e}{e}{e}", "then_trigger": [
                {"type": "copy_permanent", "params": {
                    "target_kind": "permanent_you_control", "add_types": ["Artifact", "Creature"],
                    "set_power": 5, "set_toughness": 5, "haste": True,
                }},
                {"type": "create_delayed_trigger", "params": {
                    "step": "end", "scope": "any", "capture": "previous_or_self",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                }},
            ]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Saheeli, Radiant Creator", _saheeli_radiant_creator)
