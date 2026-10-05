from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ojer_axonil_deepest_might() -> list[AbilitySpec]:
    """Trample
    If a red source you control would deal an amount of noncombat damage
    less than Ojer Axonil's power to an opponent, that source deals
    damage equal to Ojer Axonil's power instead.
    When Ojer Axonil dies, return it to the battlefield tapped and
    transformed under its owner's control.

    — Ojer Axonil, Deepest Might. New replacement `damage_floor_from_
    source_power` — `_additional_damage_replacement`'s floor-shaped
    sibling, reading the live threshold/replacement amount off this same
    source's own current power rather than a flat bonus. The death trigger
    reuses `ReturnSelfFromGraveyardEffect`'s existing ``transformed`` flag
    (also fixing a dormant bug along the way: its ``tapped`` param had
    never actually been applied — see the effect's own docstring).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("damage_floor_from_source_power", {"colors": ["R"]})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard_untargeted", {
                "destination": "battlefield", "tapped": True, "transformed": True,
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Ojer Axonil, Deepest Might // Temple of Power", _ojer_axonil_deepest_might)
