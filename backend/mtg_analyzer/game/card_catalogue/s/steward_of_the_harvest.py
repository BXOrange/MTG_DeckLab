from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _steward_of_the_harvest() -> list[AbilitySpec]:
    """When this creature enters, exile up to three target land cards from your graveyard.
    Creatures you control have all activated abilities of all land cards exiled with this creature.

    — PLAY-ALL Step 2 (Sultai Arisen). The ETB is `exile` over up to three own-graveyard land cards with
    ``track_exiled_with`` (the accumulating `GameObject.exiled_with_ids` list Agatha's Soul Cauldron reads). The static
    is the same `grant_borrowed_activated_ability` — here ``creature_only=False`` because the donors are land cards —
    so every creature you control gets one fresh copy of each exiled land's activated abilities (RULE 201.5b), mana
    abilities included.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "graveyard_land", "count": 3, "optional": True, "track_exiled_with": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "creatures_you_control", "creature_only": False,
            })],
        ),
    ]


register("Steward of the Harvest", _steward_of_the_harvest)
