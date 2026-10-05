from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _misleading_signpost() -> list[AbilitySpec]:
    """Flash
    When this artifact enters during the declare attackers step, you may reselect which player or
    permanent target attacking creature is attacking. (It can't attack its controller or their
    permanents.)
    {T}: Add {U}.

    — Keen Engineering deck batch. Flash is a keyword and the mana ability is read off the printed
    text. The ETB is the new `reselect_attack` (`ReselectAttackEffect` + the `reselect_attack` choice):
    its target is any attacking creature and its controller's legal defenders are offered. The
    "during the declare attackers step" intervening-if (RULE 603.4) is the new ``during_step``
    condition, on the trigger and on the effect.
    """
    gate = {"kind": "during_step", "step": "declare_attackers"}
    return [
        AbilitySpec("keyword", [], keyword={"name": "flash"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("reselect_attack", {}, condition=gate)],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}, "active_if": gate},
        ),
    ]


register("Misleading Signpost", _misleading_signpost)
