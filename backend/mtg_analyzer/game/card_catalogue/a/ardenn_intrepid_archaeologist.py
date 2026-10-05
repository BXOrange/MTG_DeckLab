from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# "Wyleth Equip" saved-deck-priority batch (continued)
# ---------------------------------------------------------------------------


def _ardenn_intrepid_archaeologist() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, you may attach any number
    of Auras and Equipment you control to target permanent or player.
    Partner (You can have two commanders if both have partner.)

    Simplified: narrowed to attaching *one* Aura/Equipment already
    attached to something you control, to another target creature you
    control — the "any number, freely among permanents or players" mass
    rearrange has no primitive (`AttachChosenEffect`, built for Halvar's
    own single-object clause, is the closest shape this engine has).
    (Partner is bound by the keyword catalogue automatically.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_chosen", {
                "what_kind": "attached_aura_or_equipment_you_control", "to_kind": "creature_you_control",
            })],
            # Bug report, 2026-09-04 (same typo as Sam, Loyal Attendant's own
            # entry): the real step name (`game/phases.py`) is "begin_combat",
            # not "combat" — this never matched, so the ability never fired.
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
            optional=True,
        ),
    ]


register("Ardenn, Intrepid Archaeologist", _ardenn_intrepid_archaeologist)
