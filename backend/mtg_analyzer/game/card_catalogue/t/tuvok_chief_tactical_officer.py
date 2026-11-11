from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tuvok_chief_tactical_officer() -> list[AbilitySpec]:
    """Flash
    When Tuvok enters during the declare attackers step, choose up to two target attacking creatures. For each of
    them, you may reselect which player or permanent that creature is attacking. (A creature can't attack its
    controller.)

    ENG-55: Misleading Signpost's `reselect_attack` with a two-target "up to" count; each chosen creature that is
    still attacking gets its own `reselect_attack` question in turn (`RulesEngine._offer_reselect_attacks`).
    """
    gate = {"kind": "during_step", "step": "declare_attackers"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reselect_attack", {"count": 2, "optional": True}, condition=gate)],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}, "active_if": gate},
        ),
    ]


register('Tuvok, Chief Tactical Officer', _tuvok_chief_tactical_officer)
