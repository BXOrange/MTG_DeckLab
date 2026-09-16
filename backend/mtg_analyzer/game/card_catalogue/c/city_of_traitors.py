from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _city_of_traitors() -> list[AbilitySpec]:
    """When you play another land, sacrifice this land.
    {T}: Add {C}{C}.

    — City of Traitors. The mana ability is covered by the engine's mana
    model directly off the printed text (no spec needed, same as Eiganjo,
    Seat of the Empire's own `{T}: Add {W}.`). The sacrifice trigger needed
    a new ``"LAND_PLAYED"`` entry in `effect_binder._GROUP_CONTROLLER_
    EVENT_KEYS` (that event only ever carried ``player_id``) plus a stamped
    ``instance_id`` on the event itself (`GameEngine.play_land`) so the
    ``"other"`` subject-condition flag can exclude this land's own play —
    otherwise a land with no other lands yet in play would immediately
    sacrifice itself the moment it was played.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={
                "event": EventType.LAND_PLAYED,
                "condition": {"subject": "group", "type": "land", "controller": "you", "other": True},
            },
        )
    ]


register("City of Traitors", _city_of_traitors)
