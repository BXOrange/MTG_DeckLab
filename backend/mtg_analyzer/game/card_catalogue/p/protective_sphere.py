from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _protective_sphere() -> list[AbilitySpec]:
    """{1}, Pay 1 life: Prevent all damage that would be dealt to you this
    turn by a source of your choice that shares a color with the mana
    spent on this activation cost. (Colorless mana prevents no damage.)

    — The Circle of Protection-shaped chooser (`RequestPreventDamageSourceEffect`)
    narrowed by ``source_filter={"color_from_noted_mana": True}``, reading
    `ActivationCost.note_spent_color`/`GameObject.noted_mana_color`
    (Jeweled Amulet, MEC-43) instead of a printed/ETB-chosen colour — the
    new dynamic filter `combat.matches_object_filter` gained for this card.
    "Colorless mana prevents no damage" is exactly what an unset
    ``noted_mana_color`` (the {1} paid entirely with {C}) already does: the
    filter fails closed and no source matches.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_from_noted_mana": True}, "amount": "all",
            })],
            cost={"mana": "{1}", "pay_life": 1, "note_spent_color": True},
        ),
    ]


register("Protective Sphere", _protective_sphere)
