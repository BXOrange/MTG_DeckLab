from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _incinerator_of_the_guilty() -> list[AbilitySpec]:
    """Flying, trample
    Whenever this creature deals combat damage to a player, you may collect
    evidence X. When you do, this creature deals X damage to each creature
    and planeswalker that player controls.

    — PAR-30 (Collect Evidence / Forage / Blight residue). Flying/trample
    parse on their own; only the dynamic-X collect-evidence trigger is
    hand-authored (`CollectEvidenceXThenBoardDamageEffect` — see its
    docstring for the "X = maximum available evidence" simplification and
    why the reflexive "when you do" is folded in).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("collect_evidence_x_then_board_damage", {})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Incinerator of the Guilty", _incinerator_of_the_guilty)
