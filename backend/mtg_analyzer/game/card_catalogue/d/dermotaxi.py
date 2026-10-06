from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dermotaxi() -> list[AbilitySpec]:
    """Imprint — As this Vehicle enters, exile a creature card from a graveyard.
    Tap two untapped creatures you control: Until end of turn, this Vehicle becomes a copy of the exiled card, except it's a Vehicle artifact in addition to its other types.

    — PLAY-ALL (Shorikai Vehicles). The imprint is Chrome Mox's `imprint` widened with ``pool: graveyards`` (a mandatory exile of a creature card from any
    graveyard, remembered in `linked_exile_id`) as an enters trigger rather than a true "as enters" replacement. The activation pays the parser's
    tap-two-creatures cost and runs the new `become_copy_of_imprinted_until_eot` (`become_copy_until_end_of_turn` plus the artifact/Vehicle additions).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("imprint", {"pool": "graveyards", "include_card_type": "creature", "optional": False})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_of_imprinted_until_eot", {"add_types": ["artifact"], "add_subtypes": ["Vehicle"]})],
            cost={"text": "tap two untapped creatures you control"},
        ),
    ]


register("Dermotaxi", _dermotaxi)
