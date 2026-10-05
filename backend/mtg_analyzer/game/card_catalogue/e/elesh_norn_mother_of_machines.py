from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elesh_norn_mother_of_machines() -> list[AbilitySpec]:
    """Elesh Norn, Mother of Machines (Legendary Creature — Phyrexian
    Praetor, {4}{W})

    "Vigilance
    If a permanent entering causes a triggered ability of a permanent you
    control to trigger, that ability triggers an additional time.
    Permanents entering don't cause abilities of permanents your opponents
    control to trigger."

    Vigilance is already parser-claimable. The trigger-doubling clause is
    `TriggerDoublerEffect`'s new ``cause_filter`` scoping (MEC-40, unscoped
    by the doubled permanent's own type, unlike Roaming Throne's
    ``chosen_type`` gate). The suppression clause reuses the standing
    ``trigger_prohibition`` static (Tocatli Honor Guard/Torpor Orb-shaped)
    widened with a new ``scope="opponents"`` (`continuous.trigger_
    suppressed_for`), since the printed clause silences only *opponents'*
    triggers, not the controller's own.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {
                "cause": {
                    "event": "ENTERS_BATTLEFIELD",
                    "condition": {"subject": "group", "controller": "any", "other": False},
                },
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_prohibition", {"event": EventType.ENTERS_BATTLEFIELD, "scope": "opponents"})],
        ),
    ]


register("Elesh Norn, Mother of Machines", _elesh_norn_mother_of_machines)
