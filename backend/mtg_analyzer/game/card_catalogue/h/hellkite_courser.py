from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hellkite_courser() -> list[AbilitySpec]:
    """Flying, haste
    When this creature enters, you may put a commander you own from the command zone onto the battlefield. It gains haste. Return it to the command zone at the beginning of the next end step.

    — PLAY-ALL Step 2 (Temur Roar). Next of Kin's shape: an untargeted `choose_objects` over the command zone
    (``zone_to_battlefield`` — a commander is always an owned card there; the pick is optional), whose ``then``
    runs only if one was put onto the battlefield: it gains haste (`pump` on the previous pick) and a delayed
    trigger for the next end step of any player's turn (RULE 603.7) captures it and runs the new
    `return_specific_to_command_zone`. Flying/haste are printed keywords.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {
                "action": "zone_to_battlefield", "what": "permanent", "optional": True,
                "pool_zones": ["command"],
                "prompt": "Kommandeur aus der Kommandozone ins Spiel bringen",
                "then": [
                    {"type": "pump", "params": {
                        "power": 0, "toughness": 0, "keywords": ["haste"], "previous_subject": True,
                    }},
                    {"type": "create_delayed_trigger", "params": {
                        "step": "end", "scope": "any", "capture": "previous_targets",
                        "description": "Hellkite Courser: Kommandeur zurück in die Kommandozone",
                        "effects": [{"type": "return_specific_to_command_zone", "params": {}}],
                    }},
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Hellkite Courser", _hellkite_courser)
