from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 601.2c: "creatures or Vehicles you control" -- a chosen target is one if it is a creature or a Vehicle.
_CREATURE_OR_VEHICLE = {"any_of": [{"card_type": "creature"}, {"subtype": "vehicle"}]}


def _arcee_acrobatic_coupe() -> list[AbilitySpec]:
    """Living metal (During your turn, this Vehicle is also a creature.)
    Whenever you cast a spell that targets one or more creatures or Vehicles you control, put that many +1/+1
    counters on Arcee. Convert Arcee.

    -- MEC-137. Back face of Arcee, Sharpshooter (converted via MEC-136); Living metal is folded in from the
    keyword catalogue and bound as a turn-scoped layer-4 type change. "That many" counts the cast spell's
    distinct chosen targets that are your creatures or Vehicles (``cast_spell_targets_matching``, RULE 115.1).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {
                    "kind": "+1/+1",
                    "count": {"kind": "cast_spell_targets_matching", "filter": _CREATURE_OR_VEHICLE, "you_control": True},
                }),
                EffectSpec("transform", {}),
            ],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_targets": {**_CREATURE_OR_VEHICLE, "you_control": True},
            },
            raw_text="whenever you cast a spell that targets 1 or more creatures or vehicles you control, put that "
                     "many +1/+1 counters on ~. convert ~.",
        ),
    ]


register("Arcee, Acrobatic Coupe", _arcee_acrobatic_coupe)
