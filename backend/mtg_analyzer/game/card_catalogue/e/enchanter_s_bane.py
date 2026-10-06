from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _enchanter_s_bane() -> list[AbilitySpec]:
    """At the beginning of your end step, target enchantment deals damage equal to its mana value to its controller unless that player sacrifices it.

    — PLAY-ALL (Endless Punishment). `choose_targets` announces the enchantment; an `optional` asked of its controller (sacrifice it) whose ``else_effects`` is the damage
    — dealt *by the targeted enchantment* (the new ``dealer_subject: previous_target``) to its controller, equal to its mana value measured from the same referent.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("choose_targets", {"kinds": ["enchantment"]}),
                EffectSpec("optional", {
                    "player": {"of": "previous_target", "as": "controller"},
                    "prompt": "Die Verzauberung opfern? (Sonst Schaden in Höhe ihres Manawerts)",
                    "effects": [{"type": "sacrifice_target", "params": {}}],
                    "else_effects": [{"type": "bind", "params": {
                        "name": "mv", "amount": {"kind": "characteristic", "characteristic": "mana_value", "of": "previous_target"},
                        "effects": [{"type": "damage", "params": {
                            "amount": "$mv", "recipient_subject": "previous_subject_controller", "dealer_subject": "previous_target",
                        }}],
                    }}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Enchanter's Bane", _enchanter_s_bane)
