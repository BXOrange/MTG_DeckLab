from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _flamescroll_celebrant() -> list[AbilitySpec]:
    """Flamescroll Celebrant // Revel in Silence (Creature — Human Shaman,
    {1}{R})

    "Whenever an opponent activates an ability that isn't a mana ability,
    this creature deals 1 damage to that player.
    {1}{R}: This creature gets +2/+0 until end of turn."

    The pump ability is already parser-claimable. The trigger is Harsh
    Mentor/Immolation Shaman's own already-shipped shape (RULE 602.2's
    `EventType.ACTIVATED_ABILITY`, which mana abilities never reach at all
    since they resolve through the separate `tap_for_mana` fast path
    instead of the stack — "isn't a mana ability" needs no extra filter),
    just copied verbatim.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 2, "toughness": 0})],
            cost={"text": "{1}{R}"},
        ),
    ]


register("Flamescroll Celebrant", _flamescroll_celebrant)
