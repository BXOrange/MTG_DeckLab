from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dermotaxi() -> list[AbilitySpec]:
    """Imprint — As this Vehicle enters, exile a creature card from a graveyard.
    Tap two untapped creatures you control: Until end of turn, this Vehicle becomes a copy of the exiled card, except it's a Vehicle artifact in addition to its other types.

    — PLAY-ALL (Shorikai Vehicles). The mandatory graveyard imprint is
    a before-entry instruction (RULE 614.12), so the linked card is already
    known when the Vehicle enters. Its tap-two-creatures activation copies
    that card until end of turn, retaining artifact and Vehicle types.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("entry_effect", {"effects": [
                {"type": "imprint", "params": {
                    "pool": "graveyards", "include_card_type": "creature", "optional": False,
                }},
            ]})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_of_imprinted_until_eot", {"add_types": ["artifact"], "add_subtypes": ["Vehicle"]})],
            cost={"text": "tap two untapped creatures you control"},
        ),
    ]


register("Dermotaxi", _dermotaxi)
