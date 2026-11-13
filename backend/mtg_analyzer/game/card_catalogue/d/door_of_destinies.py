from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _door_of_destinies() -> list[AbilitySpec]:
    """As this artifact enters, choose a creature type.
    Whenever you cast a spell of the chosen type, put a charge counter on this artifact.
    Creatures you control of the chosen type get +1/+1 for each charge counter on this artifact.

    RULE 614.12 choose-on-enter, RULE 205.3m type match, and a per-counter
    layer-7c anthem (``counters_on_self`` with ``counter_kind: charge``).
    """
    return [
        AbilitySpec("enter_replacement", [EffectSpec("choose_creature_type_on_enter", {})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "charge"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                     "spell_filter": {"subtype_from_source": True}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "subtype_from_source": True,
                "power": 1, "toughness": 1,
                "power_count": "counters_on_self", "toughness_count": "counters_on_self",
                "counter_kind": "charge",
            })],
        ),
    ]


register("Door of Destinies", _door_of_destinies)
