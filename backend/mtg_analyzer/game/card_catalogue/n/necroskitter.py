from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _necroskitter() -> list[AbilitySpec]:
    """Wither (This deals damage to creatures in the form of -1/-1 counters.)
    Whenever a creature an opponent controls with a -1/-1 counter on it
    dies, you may return that card to the battlefield under your control.

    Wither folds in from the RULE 702 keyword catalogue. The dies trigger is
    an ordinary group-subject DIES trigger (``has_counter_kind`` reads the
    event's last-known counters, RULE 603.10a) over `return_self_to_battlefield`
    aimed at the dying subject, "you may" via ``optional``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_to_battlefield", {
                "tapped": False, "under_your_control": True,
                "target_kind": "trigger_subject", "trigger_event_key": "__group_subject__",
            })],
            trigger={"event": "DIES", "condition": {
                "subject": "group", "controller": "not_you", "other": False,
                "type": "creature", "has_counter_kind": "-1/-1",
            }},
            optional=True,
        )
    ]


register("Necroskitter", _necroskitter)
