from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _koth_fire_of_resistance() -> list[AbilitySpec]:
    """+2: Search your library for a basic Mountain card, reveal it, put
    it into your hand, then shuffle.
    −3: Koth deals damage to target creature equal to the number of
    Mountains you control.
    −7: You get an emblem with "Whenever a Mountain you control enters,
    this emblem deals 4 damage to any target."

    — Imodane deck batch. "+2:" is the generalized search grammar
    (`search`, ``{"basic": True, "type": "Mountain"}``). "−3:" is
    `DealDamageEffect`'s `amount_from_count_selector` (the existing
    `lands_you_control_of_type_mountain`-shaped count already used
    elsewhere for a threshold filter, here as a magnitude instead).
    "−7:" is the quoted-emblem-at-loyalty shape `Tyvar Kell`/`Vraska,
    Golgari Queen` already established — the emblem's own trigger is a
    genuine `ENTERS_BATTLEFIELD` group condition scoped by subtype, no
    different from a permanent's own.
    """
    emblem_ability = AbilitySpec(
        "triggered",
        [EffectSpec("damage", {"amount": 4, "target_kind": "any"})],
        trigger={
            "event": EventType.ENTERS_BATTLEFIELD,
            "condition": {"subject": "group", "subtypes": ["mountain"], "controller": "you"},
        },
    )
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"basic": True, "type": "Mountain"}, "destination": "hand",
            })],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {
                "target_kind": "creature", "amount_from_count_selector": "lands_you_control_of_type_mountain",
            })],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": emblem_ability.to_dict()})],
            cost={"loyalty": -7},
        ),
    ]


register("Koth, Fire of Resistance", _koth_fire_of_resistance)
