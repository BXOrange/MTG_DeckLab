from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wort_boggart_auntie() -> list[AbilitySpec]:
    """Fear
    At the beginning of your upkeep, you may return target Goblin card from
    your graveyard to your hand.

    — Fear comes from the RULE 702 keyword catalogue. The upkeep head is
    Lorehold Archivist's (`STEP_BEGIN` + `phase_relation: "you"`), the body
    Morcant's Loyalist's subtype-scoped `return_from_graveyard`; "you may"
    is the effect's `optional` param, as on Sun Titan.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "subtype": "goblin",
                "destination": "hand", "optional": True,
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
            },
        ),
    ]


register("Wort, Boggart Auntie", _wort_boggart_auntie)
